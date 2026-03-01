"""Calibration targets from real-world blockchain metrics.

The simulator must match these baseline metrics with classical signatures
before injecting PQC transactions in Phase 2.

=== AWS Inter-Region Latency (RTT, ms) ===
Source: CloudPing.co — https://www.cloudping.co (Feb 2026)
Updated per Phase 2 live data ingestion.

=== PQC Verification Benchmarks ===
Sources:
  - wolfSSL/liboqs on Intel i7-8700 @ 3.20GHz, AVX2
    (https://www.wolfssl.com/documentation/manuals/wolfssl/appendix07.html)
    ML-DSA-44 verify: 54 µs  (18,403 ops/sec)
    ML-DSA-65 verify: 87 µs  (11,544 ops/sec)
    ML-DSA-87 verify: 140 µs (7,152 ops/sec)
  - Cloudflare PQC blog (Nov 2024)
    (https://blog.cloudflare.com/another-look-at-pq-signatures/)
    SLH-DSA-128f verification ≈ 110× ML-DSA-44 baseline → ~5,940 µs
  - TechRxiv — PQC for Verifiable Credentials
    (https://www.techrxiv.org/users/973090/articles/1346363)
    ML-DSA-65 verify: 47.9 µs (close agreement with wolfSSL)
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


# ---------------------------------------------------------------------------
# AWS CloudPing inter-region latency constants (Feb 2026)
# Source: https://www.cloudping.co  (live RTT matrix)
# Also cross-referenced with:
#   https://dev.to/aws-builders/looking-at-aws-inter-region-latency-through-distance-34eh
# ---------------------------------------------------------------------------
AWS_CLOUDPING_RTT_MS: Dict[str, Dict[str, float]] = {
    "us-east-1": {
        "us-west-2": 61.0, "eu-west-1": 69.7, "eu-central-1": 92.9,
        "ap-northeast-1": 151.5, "ap-southeast-1": 226.0,
        "ap-south-1": 185.9, "sa-east-1": 113.3, "af-south-1": 228.8,
    },
    "us-west-2": {
        "eu-west-1": 128.6, "eu-central-1": 152.8,
        "ap-northeast-1": 108.4, "ap-southeast-1": 170.7,
        "ap-south-1": 232.5, "sa-east-1": 173.9, "af-south-1": 288.5,
    },
    "eu-west-1": {
        "eu-central-1": 21.7, "ap-northeast-1": 203.3,
        "ap-southeast-1": 175.4, "ap-south-1": 121.8,
        "sa-east-1": 178.7, "af-south-1": 156.1,
    },
    "eu-central-1": {
        "ap-northeast-1": 225.9, "ap-southeast-1": 160.2,
        "ap-south-1": 131.2, "sa-east-1": 203.7, "af-south-1": 156.9,
    },
    "ap-northeast-1": {
        "ap-southeast-1": 69.0, "ap-south-1": 128.1,
        "sa-east-1": 260.5, "af-south-1": 296.1,
    },
    "ap-southeast-1": {
        "ap-south-1": 62.4, "sa-east-1": 329.1, "af-south-1": 214.2,
    },
    "ap-south-1": {
        "sa-east-1": 296.9, "af-south-1": 180.7,
    },
    "sa-east-1": {
        "af-south-1": 338.3,
    },
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
