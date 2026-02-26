"""Signature aggregation models for PQC blockchain impact analysis.

Models how signature aggregation techniques can reduce the per-transaction
overhead of PQC signatures, improving throughput.

Aggregation schemes:
1. **None** -- No aggregation; each transaction carries its own signature.
2. **BLS** -- BLS12-381 aggregate signatures (constant 48-byte aggregate sig).
   NOT quantum-resistant (pairing-based, vulnerable to Shor's algorithm).
3. **Falcon Merkle Tree** -- Aggregate Falcon signatures using a Merkle tree.
   Quantum-resistant. Size grows logarithmically with batch size.
4. **ML-DSA Batch Verify** -- No size reduction, but batch verification is
   ~40% faster. Quantum-resistant.

Sources:
- BLS12-381: EIP-2537, Ethereum consensus layer specification
- Falcon aggregation: research proposals for Merkle-based aggregation
- ML-DSA batch: extrapolated from lattice signature batch verification literature
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


@dataclass(frozen=True)
class AggregationScheme:
    """Definition of a signature aggregation scheme."""
    name: str
    description: str
    quantum_resistant: Optional[bool]  # None = depends on underlying algorithm
    # Size functions take (num_sigs, base_sig_size, base_pk_size) and return bytes
    _sig_size_fn: Callable[[int, int, int], int]
    _pk_size_fn: Callable[[int, int, int], int]
    # Verification time multiplier relative to individual verification
    verification_time_factor: float
    supported_algorithms: List[str]

    def aggregated_sig_size(self, num_sigs: int, algorithm: str) -> int:
        """Compute total signature bytes for num_sigs aggregated signatures."""
        base_sig = SIGNATURE_SIZES.get(algorithm, 0)
        base_pk = PUBLIC_KEY_SIZES.get(algorithm, 0)
        return self._sig_size_fn(num_sigs, base_sig, base_pk)

    def aggregated_pk_size(self, num_sigs: int, algorithm: str) -> int:
        """Compute total public key bytes for num_sigs aggregated signatures."""
        base_sig = SIGNATURE_SIZES.get(algorithm, 0)
        base_pk = PUBLIC_KEY_SIZES.get(algorithm, 0)
        return self._pk_size_fn(num_sigs, base_sig, base_pk)

    def supports(self, algorithm: str) -> bool:
        """Check if this scheme supports the given algorithm."""
        if not self.supported_algorithms:
            return True  # empty list = supports all
        return algorithm in self.supported_algorithms


# ---------------------------------------------------------------------------
# Aggregation scheme definitions
# ---------------------------------------------------------------------------

def _no_agg_sig(n: int, base_sig: int, _base_pk: int) -> int:
    return base_sig * n


def _no_agg_pk(n: int, _base_sig: int, base_pk: int) -> int:
    return base_pk * n


def _bls_sig(n: int, _base_sig: int, _base_pk: int) -> int:
    # BLS aggregate signature is constant 48 bytes regardless of n
    return 48


def _bls_pk(n: int, _base_sig: int, _base_pk: int) -> int:
    # Individual public keys must still be provided (48 bytes each for BLS12-381)
    return 48 * n


def _falcon_tree_sig(n: int, base_sig: int, _base_pk: int) -> int:
    # Merkle tree: one signature + log2(n) hashes (32 bytes each)
    if n <= 1:
        return base_sig
    return base_sig + 32 * math.ceil(math.log2(n))


def _falcon_tree_pk(n: int, _base_sig: int, _base_pk: int) -> int:
    # Merkle root only
    return 32


def _batch_sig(n: int, base_sig: int, _base_pk: int) -> int:
    # No size reduction -- all signatures still present
    return base_sig * n


def _batch_pk(n: int, _base_sig: int, base_pk: int) -> int:
    # No PK reduction
    return base_pk * n


AGGREGATION_SCHEMES: Dict[str, AggregationScheme] = {
    "None": AggregationScheme(
        name="No Aggregation",
        description="Each transaction carries its own full signature and public key.",
        quantum_resistant=None,  # depends on underlying algo
        _sig_size_fn=_no_agg_sig,
        _pk_size_fn=_no_agg_pk,
        verification_time_factor=1.0,
        supported_algorithms=[],  # supports all
    ),
    "BLS": AggregationScheme(
        name="BLS Aggregation (BLS12-381)",
        description=(
            "BLS aggregate signatures compress n signatures into a single 48-byte "
            "aggregate. Public keys are not aggregated. NOT quantum-resistant "
            "(pairing-based, broken by Shor's algorithm)."
        ),
        quantum_resistant=False,
        _sig_size_fn=_bls_sig,
        _pk_size_fn=_bls_pk,
        verification_time_factor=1.5,  # pairing check is slower
        supported_algorithms=["BLS12-381"],
    ),
    "Falcon-Tree": AggregationScheme(
        name="Falcon Merkle Tree Aggregation",
        description=(
            "Aggregate Falcon signatures using a Merkle tree. One Falcon signature "
            "plus log2(n) x 32-byte hash nodes. Quantum-resistant. Public key "
            "replaced by 32-byte Merkle root."
        ),
        quantum_resistant=True,
        _sig_size_fn=_falcon_tree_sig,
        _pk_size_fn=_falcon_tree_pk,
        verification_time_factor=1.2,  # tree path verification overhead
        supported_algorithms=["Falcon-512", "Falcon-1024"],
    ),
    "ML-DSA-Batch": AggregationScheme(
        name="ML-DSA Batch Verification",
        description=(
            "No size reduction -- all signatures are transmitted individually. "
            "However, batch verification of multiple ML-DSA signatures is ~40% "
            "faster than individual verification. Quantum-resistant."
        ),
        quantum_resistant=True,
        _sig_size_fn=_batch_sig,
        _pk_size_fn=_batch_pk,
        verification_time_factor=0.6,  # 40% faster verification
        supported_algorithms=["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"],
    ),
}


def get_aggregation_scheme(name: str) -> AggregationScheme:
    """Get an aggregation scheme by name.

    Raises ValueError if not found.
    """
    if name not in AGGREGATION_SCHEMES:
        raise ValueError(
            f"Unknown aggregation scheme: {name}. "
            f"Valid: {list(AGGREGATION_SCHEMES.keys())}"
        )
    return AGGREGATION_SCHEMES[name]


@dataclass
class AggregationAnalysis:
    """Result of applying aggregation to a batch of transactions."""
    scheme_name: str
    algorithm: str
    batch_size: int
    # Per-transaction sizes without aggregation
    individual_sig_bytes: int
    individual_pk_bytes: int
    individual_total_bytes: int
    # Aggregated sizes (amortized per transaction)
    aggregated_sig_bytes: int           # total for the batch
    aggregated_pk_bytes: int            # total for the batch
    amortized_sig_per_tx: float         # aggregated_sig_bytes / batch_size
    amortized_pk_per_tx: float          # aggregated_pk_bytes / batch_size
    amortized_total_per_tx: float       # amortized sig + pk per tx
    # Savings
    size_reduction_pct: float           # % reduction vs no aggregation
    verification_time_factor: float     # multiplier on verify time
    quantum_resistant: Optional[bool]


def analyze_aggregation(
    algorithm: str,
    scheme_name: str,
    batch_size: int = 100,
) -> AggregationAnalysis:
    """Analyze the impact of an aggregation scheme on a batch of transactions.

    Args:
        algorithm: Signature algorithm (e.g., "Falcon-512").
        scheme_name: Aggregation scheme name (e.g., "Falcon-Tree").
        batch_size: Number of transactions in the aggregation batch.

    Returns:
        AggregationAnalysis with per-transaction amortized sizes.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if algorithm not in SIGNATURE_SIZES:
        raise ValueError(f"Unknown algorithm: {algorithm}")

    scheme = get_aggregation_scheme(scheme_name)

    if not scheme.supports(algorithm) and scheme_name != "None":
        raise ValueError(
            f"Scheme '{scheme_name}' does not support algorithm '{algorithm}'. "
            f"Supported: {scheme.supported_algorithms}"
        )

    individual_sig = SIGNATURE_SIZES[algorithm]
    individual_pk = PUBLIC_KEY_SIZES[algorithm]
    individual_total = individual_sig + individual_pk

    agg_sig = scheme.aggregated_sig_size(batch_size, algorithm)
    agg_pk = scheme.aggregated_pk_size(batch_size, algorithm)

    amortized_sig = agg_sig / batch_size
    amortized_pk = agg_pk / batch_size
    amortized_total = amortized_sig + amortized_pk

    no_agg_total = individual_total * batch_size
    agg_total = agg_sig + agg_pk
    reduction = ((no_agg_total - agg_total) / no_agg_total * 100) if no_agg_total > 0 else 0.0

    qr = scheme.quantum_resistant
    if qr is None:
        # Depends on algorithm -- classical sigs are not QR
        qr = algorithm not in {"Ed25519", "ECDSA", "Schnorr", "BLS12-381"}

    return AggregationAnalysis(
        scheme_name=scheme_name,
        algorithm=algorithm,
        batch_size=batch_size,
        individual_sig_bytes=individual_sig,
        individual_pk_bytes=individual_pk,
        individual_total_bytes=individual_total,
        aggregated_sig_bytes=agg_sig,
        aggregated_pk_bytes=agg_pk,
        amortized_sig_per_tx=round(amortized_sig, 2),
        amortized_pk_per_tx=round(amortized_pk, 2),
        amortized_total_per_tx=round(amortized_total, 2),
        size_reduction_pct=round(reduction, 2),
        verification_time_factor=scheme.verification_time_factor,
        quantum_resistant=qr,
    )


def compare_aggregation_schemes(
    algorithm: str,
    batch_size: int = 100,
) -> List[AggregationAnalysis]:
    """Compare all compatible aggregation schemes for an algorithm."""
    results = []
    for name, scheme in AGGREGATION_SCHEMES.items():
        if scheme.supports(algorithm) or name == "None":
            results.append(analyze_aggregation(algorithm, name, batch_size))
    return results
