"""Chain configuration dataclass and chain-specific parameters.

Defines the key parameters that differ between blockchains:
- Block time (slot time)
- Block size limits
- Base transaction overhead
- Baseline signature algorithm
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ChainConfig:
    """Configuration parameters for a blockchain network.

    All sizes in bytes, all times in milliseconds.
    """

    name: str
    block_time_ms: float          # Time between blocks/slots
    block_size_limit: int         # Maximum block size in bytes
    base_tx_overhead: int         # Non-signature transaction overhead
    baseline_algorithm: str       # Default signature algorithm

    # Network parameters
    target_validators: int        # Typical validator count
    gossip_fanout: int            # Peers to forward to in gossip

    # Calibration target: expected stale/skip rate with classical sigs
    baseline_stale_rate: float


# Chain-specific configurations
# Sources:
# - Solana: https://docs.solana.com
# - Bitcoin: BIP 141, typical network observations
# - Ethereum: EIP-4844, consensus specs

CHAIN_CONFIGS: Dict[str, ChainConfig] = {
    "solana": ChainConfig(
        name="Solana",
        block_time_ms=400,            # 400ms slots
        block_size_limit=6_000_000,   # 6 MB practical (32 MB theoretical)
        base_tx_overhead=250,         # Transaction header, accounts, etc.
        baseline_algorithm="Ed25519",
        target_validators=1500,       # Mainnet validator count
        gossip_fanout=200,            # Turbine fanout (high for speed)
        baseline_stale_rate=0.05,     # ~5% slot skip rate
    ),
    "bitcoin": ChainConfig(
        name="Bitcoin",
        block_time_ms=600_000,        # 10 minutes
        block_size_limit=4_000_000,   # 4 MWU (weight units)
        base_tx_overhead=180,         # Version, locktime, inputs/outputs
        baseline_algorithm="ECDSA",
        target_validators=15000,      # Full nodes (no PoS validators)
        gossip_fanout=8,              # Conservative gossip
        baseline_stale_rate=0.005,    # <1% orphan rate
    ),
    "ethereum": ChainConfig(
        name="Ethereum",
        block_time_ms=12_000,         # 12 seconds
        block_size_limit=30_000_000,  # 30M gas (2024 baseline)
        base_tx_overhead=21000,       # Base gas (not bytes, but using for consistency)
        baseline_algorithm="ECDSA",
        target_validators=800000,     # Active validators in PoS
        gossip_fanout=16,             # Moderate gossip
        baseline_stale_rate=0.015,    # ~1.5% missed slots
    ),
}


def get_chain_config(chain: str) -> ChainConfig:
    """Get configuration for a chain.

    Args:
        chain: Chain name (case-insensitive).

    Returns:
        ChainConfig for the specified chain.

    Raises:
        ValueError: If chain is not recognized.
    """
    chain_lower = chain.lower()
    if chain_lower not in CHAIN_CONFIGS:
        valid = list(CHAIN_CONFIGS.keys())
        raise ValueError(f"Unknown chain: {chain}. Valid chains: {valid}")
    return CHAIN_CONFIGS[chain_lower]
