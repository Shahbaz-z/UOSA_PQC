"""Tests for chain-specific routing strategies (Phase B).

Validates that:
1. Each routing strategy produces correct propagation plans
2. Turbine creates layered propagation
3. Compact blocks reduce relay size
4. ETH hybrid uses sqrt(N) direct + announcements
5. get_routing_strategy() returns the right strategy per chain
"""

import pytest
import random
from unittest.mock import MagicMock

from simulator.network.routing import (
    GossipRouting,
    TurbineRouting,
    CompactBlockRouting,
    EthHybridRouting,
    PropagationTask,
    get_routing_strategy,
)
from simulator.network.node import Node, NodeConfig
from simulator.network.propagation import Block


def _make_node(node_id: str, region: str = "US-East"):
    """Create a minimal node for testing."""
    config = NodeConfig(
        node_id=node_id,
        region=region,
        upload_bandwidth_mbps=1000.0,
        download_bandwidth_mbps=5000.0,
        cpu_cores=8,
        processing_power_factor=1.0,
        is_validator=True,
        stake_weight=1.0,
    )
    return Node(config, env=None)


def _make_block(proposer_id: str = "v0", size_bytes: int = 1_000_000):
    """Create a minimal block for testing."""
    block = Block(
        block_hash="block_1",
        parent_hash="genesis",
        height=1,
        proposer_id=proposer_id,
        timestamp_ms=0.0,
    )
    # Override size_bytes since we have no transactions
    block.size_bytes = size_bytes
    return block


class TestGossipRouting:
    """Tests for basic gossip routing (baseline)."""

    def test_selects_up_to_fanout_peers(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(20)}
        sender = nodes["v0"]
        block = _make_block("v0", size_bytes=500_000)
        already_seen = {"v0"}

        routing = GossipRouting(fanout=8)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 8
        assert all(t.size_bytes == 500_000 for t in tasks)
        assert all(not t.is_compact for t in tasks)

    def test_excludes_already_seen(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(5)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0", "v1", "v2", "v3"}

        routing = GossipRouting(fanout=8)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 1  # Only v4 available
        assert tasks[0].receiver_id == "v4"

    def test_returns_empty_when_all_seen(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(3)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0", "v1", "v2"}

        routing = GossipRouting(fanout=8)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 0


class TestTurbineRouting:
    """Tests for Solana Turbine-like routing."""

    def test_sends_to_fanout_layer0_nodes(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(300)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0"}

        routing = TurbineRouting(fanout=200)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 200
        assert all(t.layer == 0 for t in tasks)
        assert all(t.sender_id == "v0" for t in tasks)

    def test_caps_at_available_nodes(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(10)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0"}

        routing = TurbineRouting(fanout=200)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 9  # 10 nodes minus sender

    def test_all_receivers_are_unique(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(50)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0"}

        routing = TurbineRouting(fanout=30)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        receiver_ids = [t.receiver_id for t in tasks]
        assert len(receiver_ids) == len(set(receiver_ids))


class TestCompactBlockRouting:
    """Tests for Bitcoin compact block relay."""

    def test_proposer_sends_full_blocks(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(20)}
        sender = nodes["v0"]
        block = _make_block("v0", size_bytes=1_000_000)
        already_seen = {"v0"}

        routing = CompactBlockRouting(fanout=8, compact_fraction=0.10)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 8
        # Proposer sends full blocks
        assert all(t.size_bytes == 1_000_000 for t in tasks)
        assert all(not t.is_compact for t in tasks)

    def test_relay_sends_compact_blocks(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(20)}
        # v1 is relaying (not the proposer)
        sender = nodes["v1"]
        block = _make_block("v0", size_bytes=1_000_000)  # proposer is v0
        already_seen = {"v0", "v1"}

        routing = CompactBlockRouting(fanout=8, compact_fraction=0.10)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 8
        # Relay sends compact blocks (10% of full size)
        for t in tasks:
            assert t.is_compact
            assert t.size_bytes == 100_000  # 10% of 1MB

    def test_compact_fraction_configurable(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(20)}
        sender = nodes["v1"]
        block = _make_block("v0", size_bytes=2_000_000)
        already_seen = {"v0", "v1"}

        routing = CompactBlockRouting(fanout=4, compact_fraction=0.05)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        # 5% of 2MB = 100,000 bytes
        assert all(t.size_bytes == 100_000 for t in tasks)


class TestEthHybridRouting:
    """Tests for Ethereum hybrid propagation."""

    def test_splits_direct_and_announcement(self):
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(50)}
        sender = nodes["v0"]
        block = _make_block("v0", size_bytes=500_000)
        already_seen = {"v0"}

        routing = EthHybridRouting(fanout=16)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        assert len(tasks) == 16

        # sqrt(16) = 4 direct sends
        direct = [t for t in tasks if not t.is_compact]
        announce = [t for t in tasks if t.is_compact]

        assert len(direct) == 4
        assert len(announce) == 12

        # Direct sends have full block size
        assert all(t.size_bytes == 500_000 for t in direct)
        # Announcements have small size
        assert all(t.size_bytes == 100 for t in announce)

    def test_at_least_one_direct_send(self):
        """Even with few peers, at least 1 gets direct propagation."""
        nodes = {f"v{i}": _make_node(f"v{i}") for i in range(3)}
        sender = nodes["v0"]
        block = _make_block("v0")
        already_seen = {"v0"}

        routing = EthHybridRouting(fanout=2)
        tasks = routing.plan_propagation(sender, block, nodes, already_seen, random.Random(42))

        direct = [t for t in tasks if not t.is_compact]
        assert len(direct) >= 1


class TestGetRoutingStrategy:
    """Tests for the factory function."""

    def test_solana_gets_turbine(self):
        strategy = get_routing_strategy("solana")
        assert isinstance(strategy, TurbineRouting)
        assert strategy.fanout == 200

    def test_bitcoin_gets_compact(self):
        strategy = get_routing_strategy("bitcoin")
        assert isinstance(strategy, CompactBlockRouting)
        assert strategy.fanout == 8

    def test_ethereum_gets_hybrid(self):
        strategy = get_routing_strategy("ethereum")
        assert isinstance(strategy, EthHybridRouting)

    def test_unknown_gets_gossip(self):
        strategy = get_routing_strategy("unknown_chain")
        assert isinstance(strategy, GossipRouting)

    def test_case_insensitive(self):
        assert isinstance(get_routing_strategy("Solana"), TurbineRouting)
        assert isinstance(get_routing_strategy("BITCOIN"), CompactBlockRouting)
