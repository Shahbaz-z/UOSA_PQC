"""Network topology with geographic latency modeling.

Uses AWS CloudPing inter-region latency data as baseline, with
log-normal stochastic jitter for realistic variance.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.network.node import Node


@dataclass(frozen=True)
class Region:
    """Geographic region with base characteristics.

    Coordinates are approximate data center locations for
    distance-based latency estimation when no direct measurement exists.
    """

    name: str
    latitude: float
    longitude: float
    typical_bandwidth_mbps: float  # Regional average for home validators


# Major validator regions with typical bandwidth availability
REGIONS: Dict[str, Region] = {
    "US-East": Region("US-East", 39.0, -77.0, 1000),       # Virginia
    "US-West": Region("US-West", 37.4, -122.1, 1000),      # N. California
    "EU-West": Region("EU-West", 53.3, -6.3, 800),         # Ireland
    "EU-Central": Region("EU-Central", 50.1, 8.7, 800),    # Frankfurt
    "Asia-Tokyo": Region("Asia-Tokyo", 35.7, 139.7, 600),  # Tokyo
    "Asia-Singapore": Region("Asia-Singapore", 1.3, 103.8, 500),  # Singapore
    "South-America": Region("South-America", -23.5, -46.6, 400),  # Sao Paulo
    "Australia": Region("Australia", -33.9, 151.2, 500),   # Sydney
}


# AWS CloudPing inter-region latencies (one-way, milliseconds)
# Source: https://www.cloudping.co/grid (real-world measurements)
# Updated per Quant Lead review with corrected values
#
# Format: (region_a, region_b) -> latency_ms
# Matrix is symmetric: (a, b) and (b, a) have the same latency
BASE_LATENCY_MATRIX: Dict[Tuple[str, str], float] = {
    # Keys are SORTED alphabetically for consistent lookup
    # US internal
    ("US-East", "US-West"): 62,

    # US-East to others (updated per Quant Lead)
    ("EU-West", "US-East"): 75,         # Corrected from 85
    ("EU-Central", "US-East"): 89,
    ("Asia-Tokyo", "US-East"): 155,     # Corrected from 165
    ("Asia-Singapore", "US-East"): 230,
    ("South-America", "US-East"): 120,
    ("Australia", "US-East"): 200,

    # US-West to others (updated per Quant Lead)
    ("EU-West", "US-West"): 138,
    ("EU-Central", "US-West"): 135,     # Corrected from 145
    ("Asia-Tokyo", "US-West"): 108,
    ("Asia-Singapore", "US-West"): 170,
    ("South-America", "US-West"): 180,
    ("Australia", "US-West"): 145,

    # EU internal
    ("EU-Central", "EU-West"): 25,

    # EU to Asia/others (updated per Quant Lead)
    ("Asia-Tokyo", "EU-West"): 230,
    ("Asia-Singapore", "EU-West"): 160,  # Corrected from 175
    ("EU-West", "South-America"): 200,
    ("Australia", "EU-West"): 280,
    ("Asia-Tokyo", "EU-Central"): 240,
    ("Asia-Singapore", "EU-Central"): 165,
    ("EU-Central", "South-America"): 220,
    ("Australia", "EU-Central"): 290,

    # Asia internal and to others
    ("Asia-Singapore", "Asia-Tokyo"): 70,
    ("Asia-Tokyo", "South-America"): 280,
    ("Asia-Tokyo", "Australia"): 120,
    ("Asia-Singapore", "South-America"): 340,
    ("Asia-Singapore", "Australia"): 95,

    # South America to Australia
    ("Australia", "South-America"): 320,
}


def _normalize_region_pair(a: str, b: str) -> Tuple[str, str]:
    """Normalize region pair to canonical order for matrix lookup."""
    return tuple(sorted([a, b]))


@dataclass
class NetworkTopology:
    """Network topology with nodes and latency modeling.

    Provides:
    - Node registry and lookup
    - Geographic latency calculation with stochastic jitter
    - Propagation delay computation (latency + bandwidth)
    """

    nodes: Dict[str, "Node"] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(42))

    # Jitter parameters for log-normal distribution
    # CV = coefficient of variation = std/mean
    # Network jitter follows log-normal because delays are multiplicative
    jitter_cv: float = 0.15  # 15% coefficient of variation

    def add_node(self, node: "Node") -> None:
        """Register a node in the topology."""
        self.nodes[node.config.node_id] = node

    def get_node(self, node_id: str) -> "Node":
        """Get a node by ID. Raises KeyError if not found."""
        return self.nodes[node_id]

    def get_base_latency(self, region_a: str, region_b: str) -> float:
        """Get base latency between two regions (ms).

        Returns:
            One-way latency in milliseconds.
        """
        if region_a == region_b:
            return 1.0  # Same region: ~1ms intra-datacenter

        key = _normalize_region_pair(region_a, region_b)
        return BASE_LATENCY_MATRIX.get(key, 150.0)  # Default 150ms if unknown

    def sample_latency(self, region_a: str, region_b: str) -> float:
        """Sample latency with stochastic jitter (log-normal).

        Network latency follows a log-normal distribution because:
        1. Latency is always positive (log-normal has positive support)
        2. Network delays are products of queuing, propagation, routing
           delays (Central Limit Theorem -> log-normal)
        3. Empirical measurements confirm heavy right tails

        Returns:
            Sampled one-way latency in milliseconds.
        """
        import math

        base = self.get_base_latency(region_a, region_b)

        # Log-normal parameterization:
        # If X ~ LogNormal(mu, sigma), then:
        #   median(X) = exp(mu)
        #   CV(X) = sqrt(exp(sigma^2) - 1)
        #
        # We want median = base, CV = jitter_cv
        # Solving: sigma = sqrt(log(cv^2 + 1))
        #          mu = log(base) - sigma^2/2
        sigma_sq = math.log(self.jitter_cv ** 2 + 1)
        sigma = math.sqrt(sigma_sq)
        mu = math.log(base) - sigma_sq / 2

        return self.rng.lognormvariate(mu, sigma)

    def compute_propagation_delay(
        self,
        sender: "Node",
        receiver: "Node",
        size_bytes: int,
    ) -> float:
        """Total propagation delay: latency + bandwidth-limited transmission.

        Formula:
            delay = geographic_latency + (size_bytes * 8) / effective_bandwidth

        Where effective_bandwidth = min(sender_upload, receiver_download)

        This models the physical reality that:
        1. Packets must traverse geographic distance (speed of light + routing)
        2. Data transfer is limited by the bottleneck bandwidth

        Args:
            sender: Sending node.
            receiver: Receiving node.
            size_bytes: Data size in bytes.

        Returns:
            Total delay in milliseconds.
        """
        # Geographic latency with jitter
        geo_latency = self.sample_latency(sender.config.region, receiver.config.region)

        # Bandwidth bottleneck
        effective_bw_mbps = min(
            sender.config.upload_bandwidth_mbps,
            receiver.config.download_bandwidth_mbps,
        )

        # Transmission time: size_bytes -> megabits -> time
        if effective_bw_mbps <= 0:
            transmission_time_ms = float("inf")
        else:
            size_megabits = (size_bytes * 8) / 1_000_000
            transmission_time_ms = (size_megabits / effective_bw_mbps) * 1000

        return geo_latency + transmission_time_ms

    def get_validators(self) -> List["Node"]:
        """Get all validator nodes (can propose blocks)."""
        return [n for n in self.nodes.values() if n.config.is_validator]

    def get_full_nodes(self) -> List["Node"]:
        """Get all non-validator full nodes."""
        return [n for n in self.nodes.values() if not n.config.is_validator]

    def get_nodes_by_region(self, region: str) -> List["Node"]:
        """Get all nodes in a specific region."""
        return [n for n in self.nodes.values() if n.config.region == region]

    def node_count(self) -> int:
        """Total number of nodes in the network."""
        return len(self.nodes)

    def validator_count(self) -> int:
        """Number of validator nodes."""
        return len(self.get_validators())
