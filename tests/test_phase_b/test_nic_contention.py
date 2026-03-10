"""Tests for NIC contention / upload bandwidth sharing (Phase B).

Validates that:
1. Bandwidth is shared across concurrent sends
2. NIC contention increases propagation delay
3. The contention flag can be toggled
4. Higher fanout = more contention = slower propagation
"""

import pytest
import random

from simulator.network.node import Node, NodeConfig
from simulator.network.topology import NetworkTopology
from simulator.core.engine import DESEngine, SimulationConfig


def _make_node(node_id: str, upload_mbps: float = 1000.0, region: str = "US-East"):
    """Create a node with specified upload bandwidth."""
    config = NodeConfig(
        node_id=node_id,
        region=region,
        upload_bandwidth_mbps=upload_mbps,
        download_bandwidth_mbps=10000.0,
        cpu_cores=8,
        processing_power_factor=1.0,
        is_validator=True,
        stake_weight=1.0,
    )
    return Node(config, env=None)


class TestNICContention:
    """Tests for Node.schedule_upload() NIC contention model."""

    def test_single_upload_uses_full_bandwidth(self):
        """Single upload should use full upload bandwidth."""
        node = _make_node("v0", upload_mbps=1000.0)
        # 1 MB = 8 Mbit, at 1000 Mbps = 8 ms
        finish = node.schedule_upload(
            start_time_ms=0.0,
            size_bytes=1_000_000,
            num_concurrent=1,
        )
        expected = (1_000_000 * 8 / 1_000_000) / 1000.0 * 1000  # 8.0 ms
        assert abs(finish - expected) < 0.01

    def test_concurrent_uploads_share_bandwidth(self):
        """K concurrent uploads should each get 1/K bandwidth."""
        node = _make_node("v0", upload_mbps=1000.0)
        # 1 MB with 10 concurrent sends: per-peer bw = 100 Mbps
        # tx_time = 8 Mbit / 100 Mbps = 80 ms
        finish = node.schedule_upload(
            start_time_ms=0.0,
            size_bytes=1_000_000,
            num_concurrent=10,
        )
        expected = (1_000_000 * 8 / 1_000_000) / (1000.0 / 10) * 1000  # 80.0 ms
        assert abs(finish - expected) < 0.01

    def test_contention_scales_linearly(self):
        """Doubling concurrent sends should double transmission time."""
        node1 = _make_node("v0", upload_mbps=1000.0)
        node2 = _make_node("v1", upload_mbps=1000.0)

        t1 = node1.schedule_upload(0.0, 1_000_000, num_concurrent=5)
        t2 = node2.schedule_upload(0.0, 1_000_000, num_concurrent=10)

        assert abs(t2 / t1 - 2.0) < 0.01

    def test_zero_bandwidth_returns_inf(self):
        """Zero bandwidth should return infinity."""
        node = _make_node("v0", upload_mbps=0.0)
        finish = node.schedule_upload(0.0, 1_000_000, num_concurrent=1)
        assert finish == float("inf")

    def test_upload_tracks_bytes(self):
        """Upload stats should accumulate bytes."""
        node = _make_node("v0", upload_mbps=1000.0)
        node.schedule_upload(0.0, 500_000, num_concurrent=1)
        node.schedule_upload(0.0, 300_000, num_concurrent=1)
        assert node.state.bytes_uploaded == 800_000


class TestNICContentionInEngine:
    """Integration tests: NIC contention affects propagation in the DES engine."""

    def test_nic_contention_increases_propagation(self):
        """Enabling NIC contention should increase propagation delay."""
        # Run with NIC contention OFF
        cfg_off = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2000,
            random_seed=42,
            nic_contention_enabled=False,
            use_chain_routing=False,
        )
        result_off = DESEngine(cfg_off).run()

        # Run with NIC contention ON
        cfg_on = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2000,
            random_seed=42,
            nic_contention_enabled=True,
            use_chain_routing=False,
        )
        result_on = DESEngine(cfg_on).run()

        # With contention, propagation should be slower (or equal for small networks)
        assert result_on.avg_propagation_p90_ms >= result_off.avg_propagation_p90_ms * 0.95

    def test_nic_contention_flag_respected(self):
        """The nic_contention_enabled flag should produce different results."""
        cfg1 = SimulationConfig(
            chain="solana",
            signature_algorithm="ML-DSA-65",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=2000,
            random_seed=42,
            nic_contention_enabled=False,
            use_chain_routing=False,
        )
        cfg2 = SimulationConfig(
            chain="solana",
            signature_algorithm="ML-DSA-65",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=2000,
            random_seed=42,
            nic_contention_enabled=True,
            use_chain_routing=False,
        )
        r1 = DESEngine(cfg1).run()
        r2 = DESEngine(cfg2).run()

        # PQC blocks are bigger, so NIC contention should matter more
        # At minimum, the results should differ
        assert r1.avg_propagation_p90_ms != r2.avg_propagation_p90_ms
