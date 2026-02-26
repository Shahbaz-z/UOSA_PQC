"""Calibration targets from real-world blockchain metrics.

The simulator must match these baseline metrics with classical signatures
before injecting PQC transactions in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class CalibrationTarget:
    """Calibration target for a metric with acceptable tolerance.

    The simulator is considered calibrated if the measured value
    falls within [target * (1 - tolerance), target * (1 + tolerance)].
    """

    metric: str
    target_value: float
    tolerance_pct: float  # Acceptable deviation (e.g., 0.30 = 30%)
    source: str           # Citation for the value

    @property
    def min_acceptable(self) -> float:
        """Lower bound of acceptable range."""
        return self.target_value * (1 - self.tolerance_pct)

    @property
    def max_acceptable(self) -> float:
        """Upper bound of acceptable range."""
        return self.target_value * (1 + self.tolerance_pct)

    def is_calibrated(self, actual: float) -> bool:
        """Check if actual value falls within acceptable range."""
        return self.min_acceptable <= actual <= self.max_acceptable


# Calibration targets from public chain data and research
# All propagation times in milliseconds, rates as fractions

SOLANA_TARGETS: Dict[str, CalibrationTarget] = {
    "propagation_p90_ms": CalibrationTarget(
        metric="propagation_p90_ms",
        target_value=1500.0,  # 1.5 seconds to reach 90% of validators
        tolerance_pct=0.30,
        source="Solana Beach explorer, validator gossip metrics (2024)",
    ),
    "stale_rate": CalibrationTarget(
        metric="stale_rate",
        target_value=0.05,  # 5% slot skip rate
        tolerance_pct=0.50,  # Wide tolerance due to network variability
        source="Solana validator documentation, typical skip rate",
    ),
}

BITCOIN_TARGETS: Dict[str, CalibrationTarget] = {
    "propagation_p90_ms": CalibrationTarget(
        metric="propagation_p90_ms",
        target_value=10000.0,  # ~10 seconds for 90% coverage
        tolerance_pct=0.30,
        source="DSN Bitcoin monitoring, compact block propagation (2023)",
    ),
    "stale_rate": CalibrationTarget(
        metric="stale_rate",
        target_value=0.005,  # <1% orphan rate
        tolerance_pct=0.50,
        source="Bitcoin Wiki, orphan block statistics",
    ),
}

ETHEREUM_TARGETS: Dict[str, CalibrationTarget] = {
    "propagation_p90_ms": CalibrationTarget(
        metric="propagation_p90_ms",
        target_value=3000.0,  # ~3 seconds for 90% coverage
        tolerance_pct=0.30,
        source="Etherscan, block propagation analytics",
    ),
    "stale_rate": CalibrationTarget(
        metric="stale_rate",
        target_value=0.015,  # ~1.5% missed slots
        tolerance_pct=0.40,
        source="beaconcha.in, missed slot statistics (2024)",
    ),
}

CALIBRATION_TARGETS: Dict[str, Dict[str, CalibrationTarget]] = {
    "solana": SOLANA_TARGETS,
    "bitcoin": BITCOIN_TARGETS,
    "ethereum": ETHEREUM_TARGETS,
}


def get_calibration_targets(chain: str) -> Dict[str, CalibrationTarget]:
    """Get calibration targets for a chain.

    Raises:
        ValueError: If chain has no calibration targets.
    """
    chain_lower = chain.lower()
    if chain_lower not in CALIBRATION_TARGETS:
        raise ValueError(
            f"No calibration targets for chain: {chain}. "
            f"Valid: {list(CALIBRATION_TARGETS.keys())}"
        )
    return CALIBRATION_TARGETS[chain_lower]
