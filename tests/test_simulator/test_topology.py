"""Tests for network topology and latency modeling."""

import pytest
import simpy

from simulator.network.topology import (
    NetworkTopology,
    REGIONS,
    BASE_LATENCY_MATRIX,
)
from simulator.network.node import Node, NodeConfig


class TestRegions:
    """Tests for region definitions."""

    def test_eight_regions_defined(self):
        """Should have 8 geographic regions."""
        assert len(REGIONS) == 8

    def test_all_regions_have_coordinates(self):
        """Each region should have latitude and longitude."""
        for name, region in REGIONS.items():
            assert -90 <= region.latitude <= 90
            assert -180 <= region.longitude <= 180

    def test_all_regions_have_bandwidth(self):
        """Each region should have typical bandwidth."""
        for name, region in REGIONS.items():
            assert region.typical_bandwidth_mbps > 0


class TestLatencyMatrix:
    """Tests for the inter-region latency matrix."""

    def test_matrix_is_complete(self):
        """Every region pair should have a defined latency."""
        regions = list(REGIONS.keys())
        for i, r1 in enumerate(regions):
            for r2 in regions[i + 1:]:
                key = tuple(sorted([r1, r2]))
                assert key in BASE_LATENCY_MATRIX, f"Missing: {key}"

    def test_latencies_are_positive(self):
        """All latencies should be positive."""
        for key, latency in BASE_LATENCY_MATRIX.items():
            assert latency > 0, f"Invalid latency for {key}: {latency}"

    def test_latencies_are_reasonable(self):
        """Latencies should be in a reasonable range (1-500ms)."""
        for key, latency in BASE_LATENCY_MATRIX.items():
            assert 1 <= latency <= 500, f"Unusual latency for {key}: {latency}"

    def test_corrected_latencies(self):
        """Verify the corrected AWS CloudPing values."""
        # Per Quant Lead review
        # Keys are normalized to sorted order
        assert BASE_LATENCY_MATRIX[tuple(sorted(["EU-West", "US-East"]))] == 75
        assert BASE_LATENCY_MATRIX[tuple(sorted(["Asia-Tokyo", "US-East"]))] == 155
        assert BASE_LATENCY_MATRIX[tuple(sorted(["Asia-Singapore", "EU-West"]))] == 160
        assert BASE_LATENCY_MATRIX[tuple(sorted(["EU-Central", "US-West"]))] == 135


class TestNetworkTopology:
    """Tests for NetworkTopology class."""

    @pytest.fixture
    def topology(self):
        """Create a topology with seed for reproducibility."""
        import random
        return NetworkTopology(rng=random.Random(42))

    @pytest.fixture
    def sample_node(self):
        """Create a sample node for testing."""
        env = simpy.Environment()
        config = NodeConfig(
            node_id="test_node",
            region="US-East",
            upload_bandwidth_mbps=1000,
            download_bandwidth_mbps=5000,
            cpu_cores=8,
            processing_power_factor=1.0,
            is_validator=True,
            stake_weight=1.0,
        )
        return Node(config, env)

    def test_same_region_latency(self, topology):
        """Same-region latency should be minimal (~1ms)."""
        latency = topology.get_base_latency("US-East", "US-East")
        assert latency == 1.0

    def test_cross_region_latency_symmetric(self, topology):
        """Latency should be symmetric between regions."""
        ab = topology.get_base_latency("US-East", "EU-West")
        ba = topology.get_base_latency("EU-West", "US-East")
        assert ab == ba

    def test_sampled_latency_has_jitter(self, topology):
        """Sampled latencies should vary due to stochastic jitter."""
        samples = [topology.sample_latency("US-East", "EU-West") for _ in range(100)]
        # Should have variation (not all identical)
        assert len(set(samples)) > 50

    def test_sampled_latency_positive(self, topology):
        """All sampled latencies should be positive."""
        for _ in range(100):
            latency = topology.sample_latency("US-East", "Asia-Tokyo")
            assert latency > 0

    def test_add_and_get_node(self, topology, sample_node):
        """Should be able to add and retrieve nodes."""
        topology.add_node(sample_node)
        retrieved = topology.get_node("test_node")
        assert retrieved.node_id == "test_node"

    def test_get_validators(self, topology):
        """Should filter to validator nodes only."""
        env = simpy.Environment()

        validator = Node(NodeConfig(
            node_id="validator_1", region="US-East",
            upload_bandwidth_mbps=1000, download_bandwidth_mbps=5000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        fullnode = Node(NodeConfig(
            node_id="fullnode_1", region="EU-West",
            upload_bandwidth_mbps=100, download_bandwidth_mbps=500,
            cpu_cores=4, processing_power_factor=1.0,
            is_validator=False, stake_weight=0.0,
        ), env)

        topology.add_node(validator)
        topology.add_node(fullnode)

        validators = topology.get_validators()
        assert len(validators) == 1
        assert validators[0].node_id == "validator_1"


class TestPropagationDelay:
    """Tests for propagation delay computation."""

    @pytest.fixture
    def topology(self):
        import random
        return NetworkTopology(rng=random.Random(42))

    def test_delay_includes_geographic_latency(self, topology):
        """Delay should include geographic component."""
        env = simpy.Environment()

        sender = Node(NodeConfig(
            node_id="sender", region="US-East",
            upload_bandwidth_mbps=10000, download_bandwidth_mbps=10000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        receiver = Node(NodeConfig(
            node_id="receiver", region="Asia-Tokyo",
            upload_bandwidth_mbps=10000, download_bandwidth_mbps=10000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        # With high bandwidth, delay is dominated by geographic latency
        delay = topology.compute_propagation_delay(sender, receiver, size_bytes=1000)

        geo_latency = topology.get_base_latency("US-East", "Asia-Tokyo")
        # Delay should be at least 50% of geo latency (accounting for jitter)
        assert delay >= geo_latency * 0.5

    def test_delay_includes_bandwidth_component(self, topology):
        """Delay should include bandwidth-limited transmission time."""
        env = simpy.Environment()

        # Slow sender
        sender = Node(NodeConfig(
            node_id="sender", region="US-East",
            upload_bandwidth_mbps=10,  # Very slow
            download_bandwidth_mbps=1000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        receiver = Node(NodeConfig(
            node_id="receiver", region="US-East",  # Same region
            upload_bandwidth_mbps=1000,
            download_bandwidth_mbps=1000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        # Large block should take significant time at 10 Mbps
        # 8 MB = 64 Mbit, at 10 Mbps = 6400 ms
        delay = topology.compute_propagation_delay(sender, receiver, size_bytes=8_000_000)

        # Should be at least 5 seconds (accounting for some variation)
        assert delay >= 5000

    def test_delay_uses_bottleneck_bandwidth(self, topology):
        """Delay should use min(upload, download) as bottleneck."""
        env = simpy.Environment()

        fast_sender = Node(NodeConfig(
            node_id="sender", region="US-East",
            upload_bandwidth_mbps=10000,  # Fast upload
            download_bandwidth_mbps=10000,
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        slow_receiver = Node(NodeConfig(
            node_id="receiver", region="US-East",
            upload_bandwidth_mbps=10000,
            download_bandwidth_mbps=10,  # Slow download
            cpu_cores=8, processing_power_factor=1.0,
            is_validator=True, stake_weight=1.0,
        ), env)

        # Despite fast sender, receiver's slow download is the bottleneck
        delay = topology.compute_propagation_delay(fast_sender, slow_receiver, size_bytes=8_000_000)
        assert delay >= 5000  # ~6400ms expected
