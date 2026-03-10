"""Mainnet observed data for calibration.

Uses publicly available aggregate statistics from blockchain mainnets.
Data collected from: validators.app, solanacompass.com, Solana Explorer,
beaconcha.in, etherscan.io, mempool.space, bitnodes.io.

These are representative values from Feb-Mar 2025 conditions.
Individual metrics may vary by +-20% depending on network conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class MainnetMetrics:
    """Observed metrics from a blockchain mainnet.

    All times in milliseconds, rates as fractions (0-1).
    """

    chain: str
    skip_rate: float              # Fraction of missed/skipped slots
    p50_propagation_ms: float     # Median block propagation time
    p90_propagation_ms: float     # 90th percentile propagation
    avg_block_time_ms: float      # Mean time between blocks
    validator_count: int          # Active validator count
    avg_tps: float                # Observed transactions per second
    vote_success_rate: float      # Fraction of successful votes
    avg_block_size_bytes: int     # Average block size
    notes: str = ""               # Data source and date context


MAINNET_DATA: Dict[str, MainnetMetrics] = {
    "solana": MainnetMetrics(
        chain="solana",
        skip_rate=0.05,                  # ~4-6%, central estimate 5%
        p50_propagation_ms=250.0,        # ~200-300ms observed
        p90_propagation_ms=600.0,        # ~500-800ms observed
        avg_block_time_ms=400.0,         # 400ms target slot time
        validator_count=1500,            # ~1,400-1,600 active
        avg_tps=3000.0,                  # ~2,000-4,000 including vote txs
        vote_success_rate=0.98,          # ~97-99%
        avg_block_size_bytes=1_200_000,  # ~0.8-1.5 MB typical
        notes="Sources: validators.app, solanacompass.com/validators/raw. "
              "Representative of Feb-Mar 2025 conditions.",
    ),
    "ethereum": MainnetMetrics(
        chain="ethereum",
        skip_rate=0.015,                 # ~1-2% missed slots
        p50_propagation_ms=500.0,        # ~400-600ms for full block
        p90_propagation_ms=2000.0,       # ~1.5-3s for large blocks
        avg_block_time_ms=12_000.0,      # 12s slot time
        validator_count=800_000,         # ~800k active validators
        avg_tps=15.0,                    # ~12-20 TPS average
        vote_success_rate=0.99,          # Very high attestation rate
        avg_block_size_bytes=80_000,     # ~50-120 KB typical
        notes="Sources: beaconcha.in, etherscan.io. "
              "Representative of Feb-Mar 2025 conditions.",
    ),
    "bitcoin": MainnetMetrics(
        chain="bitcoin",
        skip_rate=0.005,                 # <1% orphan rate
        p50_propagation_ms=2000.0,       # ~1-3s for compact blocks
        p90_propagation_ms=8000.0,       # ~5-15s for full propagation
        avg_block_time_ms=600_000.0,     # 10 minutes target
        validator_count=15_000,          # ~15k reachable full nodes
        avg_tps=7.0,                     # ~3-7 TPS
        vote_success_rate=1.0,           # N/A for Bitcoin
        avg_block_size_bytes=1_500_000,  # ~1-2 MB typical
        notes="Sources: mempool.space, bitnodes.io. "
              "Representative of Feb-Mar 2025 conditions.",
    ),
}


def get_mainnet_data(chain: str) -> MainnetMetrics:
    """Get mainnet metrics for a chain.

    Args:
        chain: Chain name (case-insensitive).

    Returns:
        MainnetMetrics for the chain.

    Raises:
        ValueError: If chain is not recognized.
    """
    chain_lower = chain.lower()
    if chain_lower not in MAINNET_DATA:
        valid = list(MAINNET_DATA.keys())
        raise ValueError(f"No mainnet data for chain: {chain}. Valid: {valid}")
    return MAINNET_DATA[chain_lower]
