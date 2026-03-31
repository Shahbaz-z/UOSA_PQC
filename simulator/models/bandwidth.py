"""Validator hardware distribution model.

Models the heterogeneous nature of blockchain validator infrastructure:
- Home validators: Consumer hardware, limited bandwidth
- Cloud validators: Standard cloud instances
- Datacenter validators: Professional infrastructure, high bandwidth

Distribution is based on public validator surveys and network analysis.
"""

from __future__ import annotations

import random
from typing import Dict

from simulator.network.node import NodeConfig


# Realistic validator hardware distribution
# Sources:
# - Solana validator requirements documentation
# - Ethereum node surveys (ethernodes.org)
# - Bitcoin node network analysis

# BUG-H NOTE — Solana home-tier bandwidth floor:
# Solana’s documented minimum hardware requirement is 300 Mbps upload.
# The home tier below (25–100 Mbps) represents nodes that would fail
# Solana’s requirements.  For Solana-specific simulations, the engine
# should use SOLANA_VALIDATOR_TIERS (see below) which floors home-tier
# upload at 300 Mbps.  This generic VALIDATOR_TIERS is retained for
# Bitcoin/Ethereum runs where lower bandwidth is realistic.
VALIDATOR_TIERS: Dict[str, Dict] = {
    "home": {
        "fraction": 0.15,  # 15% of validators are home operators
        "upload_mbps": (25, 100),       # Consumer upload speeds
        "download_mbps": (100, 500),    # Consumer download speeds
        "cpu_cores": (4, 8),            # Consumer CPUs
        "processing_factor": (0.8, 1.0),  # Slightly slower
        "stake_weight_range": (0.1, 1.0),  # Lower stake typically
    },
    "cloud": {
        "fraction": 0.50,  # 50% run on cloud infrastructure
        "upload_mbps": (500, 2000),     # Cloud instance bandwidth
        "download_mbps": (1000, 5000),
        "cpu_cores": (8, 16),           # Standard cloud instances
        "processing_factor": (1.0, 1.2),
        "stake_weight_range": (0.5, 5.0),
    },
    "datacenter": {
        "fraction": 0.35,  # 35% run professional datacenter infrastructure
        "upload_mbps": (5000, 25000),   # Dedicated servers
        "download_mbps": (10000, 50000),
        "cpu_cores": (32, 128),         # High-performance servers
        "processing_factor": (1.2, 2.0),  # Faster processing
        "stake_weight_range": (2.0, 20.0),  # Higher stake typically
    },
}


# BUG-H FIX — Solana-specific validator tiers:
# Overrides the generic home tier to enforce Solana’s minimum 300 Mbps upload.
# Source: https://docs.solana.com/running-validator/validator-reqs
# "Validators need at least 300 Mbit/s symmetric networking."
# Home-tier nodes below this threshold would be rejected by the network;
# modelling them inflates propagation delay estimates for Solana.
SOLANA_VALIDATOR_TIERS: Dict[str, Dict] = {
    **VALIDATOR_TIERS,  # cloud and datacenter tiers unchanged
    "home": {
        **VALIDATOR_TIERS["home"],
        # Raise floor to 300 Mbps (Solana minimum) — upper bound unchanged
        "upload_mbps": (300, 600),      # 300–600 Mbps: high-speed residential / business fibre
        "download_mbps": (500, 1000),
        "cpu_cores": (8, 16),           # Minimum 12 cores recommended; floor at 8
    },
}


def sample_validator_config(
    node_id: str,
    region: str,
    rng: random.Random,
    is_validator: bool = True,
    chain: str = "",
) -> NodeConfig:
    """Sample a realistic validator configuration.

    Selects a hardware tier based on the distribution, then samples
    specific values within that tier's ranges.

    Args:
        node_id: Unique identifier for the node.
        region: Geographic region.
        rng: Random number generator for reproducibility.
        is_validator: Whether this node can propose blocks.
        chain: Chain name ("solana" uses SOLANA_VALIDATOR_TIERS with 300 Mbps floor).

    Returns:
        NodeConfig with sampled hardware characteristics.
    """
    # BUG-H FIX: Solana validators must meet a 300 Mbps minimum upload requirement.
    # Use the Solana-specific tier table for Solana runs to avoid modelling
    # sub-minimum nodes that would be rejected from the network.
    tier_table = SOLANA_VALIDATOR_TIERS if chain.lower() == "solana" else VALIDATOR_TIERS

    # Select tier based on distribution
    tiers = list(tier_table.keys())
    weights = [tier_table[t]["fraction"] for t in tiers]
    tier = rng.choices(tiers, weights=weights)[0]

    spec = tier_table[tier]

    # Sample within ranges (uniform distribution)
    upload = rng.uniform(*spec["upload_mbps"])
    download = rng.uniform(*spec["download_mbps"])
    cores = rng.randint(*spec["cpu_cores"])
    processing = rng.uniform(*spec["processing_factor"])
    stake = rng.uniform(*spec["stake_weight_range"]) if is_validator else 0.0

    return NodeConfig(
        node_id=node_id,
        region=region,
        upload_bandwidth_mbps=upload,
        download_bandwidth_mbps=download,
        cpu_cores=cores,
        processing_power_factor=processing,
        is_validator=is_validator,
        stake_weight=stake,
    )


def sample_full_node_config(
    node_id: str,
    region: str,
    rng: random.Random,
) -> NodeConfig:
    """Sample a configuration for a non-validator full node.

    Full nodes tend to have more modest hardware than validators.
    """
    # Full nodes are predominantly home users with residential internet.
    # Previous implementation sampled from the lower half of the cloud tier
    # bandwidth range ([500, 1250] Mbps upload), which is 10-50× higher than
    # a typical residential full node (~10-50 Mbps upload).
    # Fix: 70% sample the home tier directly; 30% sample cloud (hosted full nodes).
    # Sources: Ethernodes.org survey (2024), Bitcoin Core hardware requirements
    tiers = ["home", "cloud"]
    weights = [0.70, 0.30]  # 70% residential, 30% cloud-hosted
    tier = rng.choices(tiers, weights=weights)[0]

    spec = VALIDATOR_TIERS[tier]

    # Sample the lower third of the tier's bandwidth range for full nodes
    # (full nodes have lower hardware requirements than validators)
    upload_cap   = spec["upload_mbps"][0]   + (spec["upload_mbps"][1]   - spec["upload_mbps"][0])   / 3
    download_cap = spec["download_mbps"][0] + (spec["download_mbps"][1] - spec["download_mbps"][0]) / 3
    upload    = rng.uniform(spec["upload_mbps"][0],   upload_cap)
    download  = rng.uniform(spec["download_mbps"][0], download_cap)
    cores     = rng.randint(spec["cpu_cores"][0], (spec["cpu_cores"][0] + spec["cpu_cores"][1]) // 2)
    processing = rng.uniform(spec["processing_factor"][0],
                             spec["processing_factor"][0]
                             + (spec["processing_factor"][1] - spec["processing_factor"][0]) / 2)

    return NodeConfig(
        node_id=node_id,
        region=region,
        upload_bandwidth_mbps=upload,
        download_bandwidth_mbps=download,
        cpu_cores=cores,
        processing_power_factor=processing,
        is_validator=False,
        stake_weight=0.0,
    )


def region_distribution() -> Dict[str, float]:
    """Default geographic distribution of validators.

    Based on observed validator distributions in major networks.
    """
    return {
        "US-East": 0.20,
        "US-West": 0.15,
        "EU-West": 0.15,
        "EU-Central": 0.15,
        "Asia-Tokyo": 0.12,
        "Asia-Singapore": 0.10,
        "South-America": 0.05,
        "Australia": 0.08,
    }
