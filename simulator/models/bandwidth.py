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


def sample_validator_config(
    node_id: str,
    region: str,
    rng: random.Random,
    is_validator: bool = True,
) -> NodeConfig:
    """Sample a realistic validator configuration.

    Selects a hardware tier based on the distribution, then samples
    specific values within that tier's ranges.

    Args:
        node_id: Unique identifier for the node.
        region: Geographic region.
        rng: Random number generator for reproducibility.
        is_validator: Whether this node can propose blocks.

    Returns:
        NodeConfig with sampled hardware characteristics.
    """
    # Select tier based on distribution
    tiers = list(VALIDATOR_TIERS.keys())
    weights = [VALIDATOR_TIERS[t]["fraction"] for t in tiers]
    tier = rng.choices(tiers, weights=weights)[0]

    spec = VALIDATOR_TIERS[tier]

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
    # Full nodes are typically home or light cloud
    tiers = ["home", "cloud"]
    weights = [0.6, 0.4]  # 60% home, 40% cloud
    tier = rng.choices(tiers, weights=weights)[0]

    spec = VALIDATOR_TIERS[tier]

    # Sample with lower end of ranges
    upload = rng.uniform(spec["upload_mbps"][0], sum(spec["upload_mbps"]) / 2)
    download = rng.uniform(spec["download_mbps"][0], sum(spec["download_mbps"]) / 2)
    cores = rng.randint(spec["cpu_cores"][0], (spec["cpu_cores"][0] + spec["cpu_cores"][1]) // 2)
    processing = rng.uniform(spec["processing_factor"][0], sum(spec["processing_factor"]) / 2)

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
