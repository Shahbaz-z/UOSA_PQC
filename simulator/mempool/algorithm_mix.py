"""Phase 2: Algorithm Mix Generator.

Weighted random sampler that produces a heterogeneous mix of classical
(Ed25519) and PQC (ML-DSA-44, ML-DSA-65, SLH-DSA-128f) signature types.

The pqc_fraction parameter controls the proportion of PQC transactions
in the mix — this is the primary independent variable for the Monte Carlo
parameter sweep in Step 4.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


# Default PQC algorithm weights (conditional on a tx being PQC)
# These reflect a plausible adoption scenario where ML-DSA-65 dominates
# PQC adoption, with some ML-DSA-44 and a smaller SLH-DSA tail.
DEFAULT_PQC_WEIGHTS: Dict[str, float] = {
    "ML-DSA-44": 0.30,
    "ML-DSA-65": 0.50,
    "SLH-DSA-128f": 0.20,
}


@dataclass
class AlgorithmMixConfig:
    """Configuration for the heterogeneous signature mix.

    Attributes:
        pqc_fraction: Fraction of transactions using PQC signatures [0.0, 1.0].
            0.0 = all classical (Ed25519), 1.0 = all PQC.
        classical_algo: Name of the classical baseline algorithm.
        pqc_weights: Relative weights for PQC algorithm selection.
            Keys must be valid algorithm names in SIGNATURE_SIZES.
    """

    pqc_fraction: float
    classical_algo: str = "Ed25519"
    pqc_weights: Dict[str, float] = None  # type: ignore

    def __post_init__(self) -> None:
        if not 0.0 <= self.pqc_fraction <= 1.0:
            raise ValueError(
                f"pqc_fraction must be in [0.0, 1.0], got {self.pqc_fraction}"
            )
        if self.pqc_weights is None:
            self.pqc_weights = dict(DEFAULT_PQC_WEIGHTS)

        # Validate all algorithms exist
        if self.classical_algo not in SIGNATURE_SIZES:
            raise ValueError(f"Unknown classical algorithm: {self.classical_algo}")
        for algo in self.pqc_weights:
            if algo not in SIGNATURE_SIZES:
                raise ValueError(f"Unknown PQC algorithm: {algo}")


class AlgorithmMixGenerator:
    """Weighted random sampler for heterogeneous signature mixes.

    Usage:
        mix = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.30),
            rng=random.Random(42),
        )
        algo_name = mix.sample()  # Returns e.g. "Ed25519" or "ML-DSA-65"
    """

    def __init__(
        self,
        config: AlgorithmMixConfig,
        rng: random.Random,
    ) -> None:
        self.config = config
        self.rng = rng

        # Pre-compute PQC selection lists
        self._pqc_algos = list(config.pqc_weights.keys())
        self._pqc_weights = list(config.pqc_weights.values())

    def sample(self) -> str:
        """Sample a single algorithm name from the mix distribution.

        Returns:
            Algorithm name string (e.g., "Ed25519", "ML-DSA-65").
        """
        if self.rng.random() < self.config.pqc_fraction:
            # PQC transaction
            return self.rng.choices(
                self._pqc_algos, weights=self._pqc_weights
            )[0]
        else:
            return self.config.classical_algo

    def sample_batch(self, n: int) -> List[str]:
        """Sample n algorithm names.

        Args:
            n: Number of samples.

        Returns:
            List of algorithm name strings.
        """
        return [self.sample() for _ in range(n)]

    def tx_size_bytes(self, algo_name: str, base_overhead: int = 250) -> int:
        """Compute transaction size for a given algorithm.

        Args:
            algo_name: Signature algorithm name.
            base_overhead: Non-signature transaction overhead in bytes.

        Returns:
            Total transaction size in bytes.
        """
        sig_size = SIGNATURE_SIZES.get(algo_name, 64)
        pk_size = PUBLIC_KEY_SIZES.get(algo_name, 32)
        return base_overhead + sig_size + pk_size
