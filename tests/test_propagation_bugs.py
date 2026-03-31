"""Regression tests for propagation-layer bugs identified in deep evaluation.

Covers:
  Bug 1 — propagation_percentile off-by-one (propagation.py)
  Bug 3 — EthHybridRouting announcement peers (routing.py + engine.py)
  Bug 4 — get_block_by_hash O(1) dict index (state.py)
  Bug 6 — Phase2 verify time cpu_cores × speed_factor separation (phase2_engine.py)
  Bug 7 — record_block_fee wired in _create_heterogeneous_block (phase2_engine.py)
  Bug 8 — schedule_upload wired into engine NIC path (engine.py)
"""

import math
import random
import pytest

from simulator.network.propagation import Block, Transaction
from simulator.network.routing import PropagationTask, EthHybridRouting
from simulator.state import SimulationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(n_seen: int, start_time: float = 0.0) -> Block:
    """Create a Block with n_seen first_seen_by entries at regular intervals."""
    block = Block(
        block_hash="b1",
        parent_hash="genesis",
        height=1,
        proposer_id="p0",
        timestamp_ms=start_time,
    )
    for i in range(n_seen):
        block.first_seen_by[f"node_{i}"] = start_time + (i + 1) * 10.0  # 10 ms apart
    return block


# ---------------------------------------------------------------------------
# Bug 1 — propagation_percentile nearest-rank correctness
# ---------------------------------------------------------------------------

class TestPropagationPercentile:
    """Verify the nearest-rank method is used, not the old floor-division."""

    def test_p90_of_10_nodes_is_9th_value(self):
        """p90 of 10 values should be the 9th value (index 8), not the 10th."""
        block = _make_block(10)
        # Values: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 ms
        # p90: ceil(10 * 90/100) - 1 = ceil(9) - 1 = 9 - 1 = 8 → value[8] = 90 ms
        p90 = block.propagation_percentile(90)
        assert p90 == pytest.approx(90.0), (
            f"p90 of 10 nodes should be 90 ms (index 8), got {p90}"
        )

    def test_p90_of_100_nodes_is_90th_value(self):
        """p90 of 100 values should be the 90th value (index 89)."""
        block = _make_block(100)
        # Values: 10, 20, ..., 1000 ms at 10 ms intervals
        # p90: ceil(100 * 90/100) - 1 = 90 - 1 = 89 → value[89] = 900 ms
        p90 = block.propagation_percentile(90)
        assert p90 == pytest.approx(900.0), (
            f"p90 of 100 nodes should be 900 ms (index 89), got {p90}"
        )

    def test_old_floor_formula_would_overshoot(self):
        """Confirm the old formula gives a different (wrong) answer."""
        n = 100
        p = 90
        # Old formula: int(100 * 90 / 100) = int(90) = 90 → index 90 → value 910
        old_index = int(n * p / 100)
        # New formula: ceil(100 * 90/100) - 1 = 90 - 1 = 89 → value 900
        new_index = max(0, math.ceil(n * p / 100) - 1)
        assert old_index == 90   # the wrong index
        assert new_index == 89   # the correct index

    def test_p50_of_odd_count(self):
        """p50 of 5 values (10, 20, 30, 40, 50) should be 30 (3rd value)."""
        block = _make_block(5)
        # ceil(5 * 50/100) - 1 = ceil(2.5) - 1 = 3 - 1 = 2 → value[2] = 30 ms
        p50 = block.propagation_percentile(50)
        assert p50 == pytest.approx(30.0)

    def test_p100_returns_last_value(self):
        """p100 should always return the maximum propagation time."""
        block = _make_block(10)
        p100 = block.propagation_percentile(100)
        assert p100 == pytest.approx(100.0)

    def test_p0_returns_first_value(self):
        """p0 should return the minimum propagation time (earliest node)."""
        block = _make_block(10)
        # ceil(10 * 0/100) - 1 = 0 - 1 = -1 → clamped to 0 → value[0] = 10 ms
        p0 = block.propagation_percentile(0)
        assert p0 == pytest.approx(10.0)

    def test_validation_percentile_same_formula(self):
        """validation_percentile should use the same nearest-rank formula."""
        block = Block(
            block_hash="b2", parent_hash="genesis", height=1,
            proposer_id="p0", timestamp_ms=0.0
        )
        for i in range(10):
            block.validated_by[f"node_{i}"] = (i + 1) * 10.0
        # p90: index 8 → 90 ms
        assert block.validation_percentile(90) == pytest.approx(90.0)

    def test_single_node_always_100_percent(self):
        """With one node, any percentile should return that node's time."""
        block = _make_block(1)
        assert block.propagation_percentile(50) == pytest.approx(10.0)
        assert block.propagation_percentile(90) == pytest.approx(10.0)
        assert block.propagation_percentile(100) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Bug 3 — EthHybridRouting: is_eth_announcement field
# ---------------------------------------------------------------------------

class TestEthHybridAnnouncementFlag:
    """Verify EthHybridRouting correctly marks announcement tasks."""

    def _make_nodes(self, n: int):
        """Return a minimal dict of mock nodes for routing tests."""
        class MockConfig:
            region = "us-east-1"
            upload_bandwidth_mbps = 1000.0
            download_bandwidth_mbps = 1000.0

        class MockNode:
            def __init__(self, nid):
                self.node_id = nid
                self.config = MockConfig()
                self._seen = set()

            def has_seen_block(self, bh):
                return bh in self._seen

        return {f"n{i}": MockNode(f"n{i}") for i in range(n)}

    def test_announcement_tasks_have_flag_set(self):
        """PropagationTask objects for announcement peers must have is_eth_announcement=True."""
        routing = EthHybridRouting(fanout=10)
        nodes = self._make_nodes(15)
        sender = nodes["n0"]

        block = Block(
            block_hash="bh1", parent_hash="g", height=1,
            proposer_id="n0", timestamp_ms=0.0,
            transactions=[Transaction(
                tx_id="t1", size_bytes=500, signature_algorithm="ECDSA",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )]
        )
        block.__post_init__()

        tasks = routing.plan_propagation(
            sender=sender, block=block,
            all_nodes={k: v for k, v in nodes.items() if k != "n0"},
            already_seen={"n0"},
            rng=random.Random(42),
        )

        direct_tasks = [t for t in tasks if not t.is_eth_announcement]
        announce_tasks = [t for t in tasks if t.is_eth_announcement]

        assert len(direct_tasks) >= 1, "Must have at least one direct-send task"
        assert len(announce_tasks) >= 1, "Must have at least one announcement task"

        # All announcement tasks must carry the announcement size, not full block
        for t in announce_tasks:
            assert t.size_bytes == EthHybridRouting.ANNOUNCEMENT_SIZE_BYTES, (
                f"Announcement task size should be {EthHybridRouting.ANNOUNCEMENT_SIZE_BYTES} B, "
                f"got {t.size_bytes} B"
            )
            assert t.is_eth_announcement is True

        # Direct tasks must carry the full block
        for t in direct_tasks:
            assert t.is_eth_announcement is False
            assert t.size_bytes == block.size_bytes

    def test_propagation_task_has_is_eth_announcement_field(self):
        """PropagationTask dataclass must have is_eth_announcement as a field."""
        task = PropagationTask(
            sender_id="a", receiver_id="b", size_bytes=100,
            is_eth_announcement=True
        )
        assert task.is_eth_announcement is True

    def test_default_is_eth_announcement_false(self):
        """PropagationTask default is_eth_announcement should be False."""
        task = PropagationTask(sender_id="a", receiver_id="b", size_bytes=500)
        assert task.is_eth_announcement is False


# ---------------------------------------------------------------------------
# Bug 4 — get_block_by_hash O(1) dict index
# ---------------------------------------------------------------------------

class TestBlockIndexO1:
    """Verify get_block_by_hash uses the dict index, not linear scan."""

    def test_register_block_populates_index(self):
        """register_block must add block to _block_index."""
        state = SimulationState(end_time_ms=60_000.0)
        block = Block(
            block_hash="bh_test", parent_hash="genesis",
            height=1, proposer_id="p0", timestamp_ms=0.0
        )
        state.register_block(block)
        assert "bh_test" in state._block_index

    def test_get_block_by_hash_returns_correct_block(self):
        """get_block_by_hash must return the registered block."""
        state = SimulationState(end_time_ms=60_000.0)
        block = Block(
            block_hash="bh_abc", parent_hash="genesis",
            height=1, proposer_id="p0", timestamp_ms=0.0
        )
        state.register_block(block)
        assert state.get_block_by_hash("bh_abc") is block

    def test_get_block_by_hash_returns_none_for_unknown(self):
        """get_block_by_hash must return None for unknown hashes."""
        state = SimulationState(end_time_ms=60_000.0)
        assert state.get_block_by_hash("nonexistent") is None

    def test_multiple_blocks_all_indexed(self):
        """All registered blocks must be findable by hash."""
        state = SimulationState(end_time_ms=60_000.0)
        blocks = []
        for i in range(50):
            b = Block(
                block_hash=f"bh_{i}", parent_hash=f"bh_{i-1}",
                height=i + 1, proposer_id="p0", timestamp_ms=float(i * 400)
            )
            state.register_block(b)
            blocks.append(b)

        for b in blocks:
            assert state.get_block_by_hash(b.block_hash) is b
        assert len(state._block_index) == 50

    def test_blocks_proposed_still_populated(self):
        """blocks_proposed list must still be populated (for result computation)."""
        state = SimulationState(end_time_ms=60_000.0)
        block = Block(
            block_hash="bh_x", parent_hash="genesis",
            height=1, proposer_id="p0", timestamp_ms=0.0
        )
        state.register_block(block)
        assert len(state.blocks_proposed) == 1
        assert state.blocks_proposed[0] is block


# ---------------------------------------------------------------------------
# Bug 6 — Phase2 verification: cpu_cores × speed_factor separation
# ---------------------------------------------------------------------------

class TestPhase2VerifyConsistency:
    """Phase2Engine._compute_heterogeneous_verify_time must match Phase1 physics."""

    def test_verify_time_phase2_applies_batch_speedup(self):
        """Phase2 applies batch_speedup for Ed25519; Phase1 does not.

        Node.verification_time_ms() (Phase 1) uses raw verify_time_us without
        batch speedup.  _compute_heterogeneous_verify_time() (Phase 2) applies
        batch_speedup for algorithms that support it (Ed25519: 0.5×).

        This means Phase 2 is MORE accurate for Ed25519 (batch verification
        is standard in validators), and the two paths correctly diverge for
        batch-verifiable algorithms.  For non-batch algorithms (ML-DSA: 1.0×)
        they should still agree.
        """
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.network.node import Node, NodeConfig
        from simulator.network.propagation import Block, Transaction
        from blockchain.verification import VERIFICATION_PROFILES

        cfg = Phase2Config(chain="solana", pqc_fraction=0.0, random_seed=0)
        engine = Phase2Engine(cfg)

        node_cfg = NodeConfig(
            node_id="test_node",
            is_validator=True,
            region="us-east-1",
            upload_bandwidth_mbps=100.0,
            download_bandwidth_mbps=100.0,
            cpu_cores=4,
            processing_power_factor=2.0,
            stake_weight=1.0,
        )
        from simulator.state import SimulationState
        ss = SimulationState(end_time_ms=60000)
        node = Node(config=node_cfg, env=ss)

        # Build a uniform Ed25519 block (10 txs, 1 sig each)
        txs_ed = [
            Transaction(
                tx_id=f"t{i}", size_bytes=250, signature_algorithm="Ed25519",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )
            for i in range(10)
        ]
        block_ed = Block(
            block_hash="bh_ed", parent_hash="g", height=1,
            proposer_id="p0", timestamp_ms=0.0, transactions=txs_ed
        )

        phase2_ed = engine._compute_heterogeneous_verify_time(block_ed, node)
        phase1_ed  = node.verification_time_ms("Ed25519", 10)

        # Fix 6: verification_time_ms now also applies batch_speedup consistently.
        # Both Phase 1 and Phase 2 apply batch_speedup, so they should now agree.
        ed_profile = VERIFICATION_PROFILES["Ed25519"]
        assert phase2_ed == pytest.approx(phase1_ed, rel=0.01), (
            f"Phase2 Ed25519 ({phase2_ed:.4f} ms) should equal Phase1 ({phase1_ed:.4f} ms) "
            f"since both now apply batch_speedup ({ed_profile.batch_speedup})"
        )

        # For non-batch algorithms (ML-DSA: batch_speedup=1.0), Phase2 and Phase1 agree
        txs_ml = [
            Transaction(
                tx_id=f"m{i}", size_bytes=3500, signature_algorithm="ML-DSA-65",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )
            for i in range(10)
        ]
        block_ml = Block(
            block_hash="bh_ml", parent_hash="g", height=1,
            proposer_id="p0", timestamp_ms=0.0, transactions=txs_ml
        )

        phase2_ml = engine._compute_heterogeneous_verify_time(block_ml, node)
        phase1_ml  = node.verification_time_ms("ML-DSA-65", 10)
        assert phase2_ml == pytest.approx(phase1_ml, rel=0.01), (
            f"Phase2 ML-DSA-65 ({phase2_ml:.4f} ms) should match Phase1 ({phase1_ml:.4f} ms) "
            "since batch_speedup=1.0 (no batch verify standard for lattice schemes)"
        )

    def test_power_factor_halves_time_cores_do_not(self):
        """Verify that processing_power_factor halves the verify duration.

        cpu_cores does NOT affect the duration returned here — it is handled
        by schedule_verification() via the _core_free_at heap, exactly as in
        Phase 1's Node.verification_time_ms() path.
        """
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.network.node import Node, NodeConfig
        from simulator.network.propagation import Block, Transaction
        from simulator.state import SimulationState

        cfg = Phase2Engine(Phase2Config(chain="solana", random_seed=0))
        txs = [
            Transaction(
                tx_id=f"t{i}", size_bytes=250, signature_algorithm="ML-DSA-65",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )
            for i in range(20)
        ]
        block = Block(
            block_hash="bh", parent_hash="g", height=1,
            proposer_id="p0", timestamp_ms=0.0, transactions=txs
        )
        ss = SimulationState(end_time_ms=60000)

        def make_node(cores, power):
            return Node(NodeConfig(
                node_id="n", is_validator=True, region="us-east-1",
                upload_bandwidth_mbps=100.0, download_bandwidth_mbps=100.0,
                cpu_cores=cores, processing_power_factor=power,
                stake_weight=1.0,
            ), env=ss)

        base       = cfg._compute_heterogeneous_verify_time(block, make_node(1, 1.0))
        more_cores = cfg._compute_heterogeneous_verify_time(block, make_node(4, 1.0))
        more_power = cfg._compute_heterogeneous_verify_time(block, make_node(1, 2.0))

        # cpu_cores does NOT change the duration returned (schedule_verification handles it)
        assert more_cores == pytest.approx(base, rel=0.01), (
            "cpu_cores should NOT change the duration from _compute_heterogeneous_verify_time; "
            "parallelism is applied by schedule_verification() via the _core_free_at heap"
        )
        # processing_power_factor DOES halve the duration (serial speed)
        assert more_power == pytest.approx(base / 2, rel=0.01), (
            "Doubling processing_power_factor should halve verify time"
        )


# ---------------------------------------------------------------------------
# Bug 7 — record_block_fee wired into _create_heterogeneous_block
# ---------------------------------------------------------------------------

class TestFeeMarketRecordBlockFee:
    """Verify the Bitcoin first-price fee market is populated on each block."""

    def test_record_block_fee_called_when_fee_market_enabled(self):
        """After a block is created, _last_block_fees must be non-empty."""
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.economics.fee_market import FeeMarketConfig

        cfg = Phase2Config(
            chain="bitcoin",
            pqc_fraction=0.0,
            lambda_tps=10.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5_000,
            random_seed=42,
            fee_market_enabled=True,
            fee_market_config=FeeMarketConfig(
                base_fee_floor=1.0,
                base_fee_ceiling=10_000.0,
                target_utilization=0.5,
                adjustment_speed=0.125,
                fee_model="first_price",
            ),
        )
        engine = Phase2Engine(cfg)
        # Pre-fill mempool
        engine._generate_transactions_until(600_000)

        # Pick a proposer and create a block
        proposer = list(engine._engine.topology.nodes.values())[0]
        block = engine._create_heterogeneous_block(proposer)

        # If transactions were selected, fees must have been recorded
        if block.tx_count > 0:
            assert len(engine._fee_market._fees_paid) > 0, (
                "record_block_fee must be called for included transactions; "
                "_fees_paid is still empty after block creation"
            )

    def test_first_price_fee_does_not_decay_when_blocks_non_empty(self):
        """With record_block_fee wired, first-price base fee should NOT decay on non-empty blocks."""
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.economics.fee_market import DynamicFeeMarket, FeeMarketConfig
        import random as rand

        fm_config = FeeMarketConfig(
            base_fee_floor=1.0, base_fee_ceiling=10_000.0,
            target_utilization=0.5, adjustment_speed=0.125,
            fee_model="first_price",
        )
        fm = DynamicFeeMarket(fm_config, rng=rand.Random(42))

        initial_fee = fm.base_fee
        # Record some fees (simulating transactions in block)
        fm.record_block_fee(50.0)
        fm.record_block_fee(30.0)
        fm.record_block_fee(40.0)

        # Update fee → should use min(30, 40, 50) = 30, not decay
        fm.update_base_fee(current_time_ms=400.0, mempool_utilization=0.5)

        # After update, base_fee = min(last_block_fees) = 30
        assert fm.base_fee == pytest.approx(30.0, rel=0.01), (
            f"First-price base_fee should be min(fees)=30, got {fm.base_fee}"
        )

    def test_first_price_decays_only_when_no_fees_recorded(self):
        """Without record_block_fee, the first-price model should decay.

        The fee_market applies 0.95 decay, but the result is clamped to
        base_fee_floor.  Start above the floor to observe the decay.
        """
        from simulator.economics.fee_market import DynamicFeeMarket, FeeMarketConfig
        import random as rand

        fm_config = FeeMarketConfig(
            fee_model="first_price",
            base_fee_floor=0.001,   # far below initial so decay is visible
            base_fee_ceiling=10_000.0,
            adjustment_speed=0.125,
        )
        fm = DynamicFeeMarket(fm_config, rng=rand.Random(42))
        # base_fee starts at base_fee_floor; set it above floor to see decay
        fm.base_fee = 100.0
        initial_fee = fm.base_fee

        # No record_block_fee calls → should decay by 5%
        fm.update_base_fee(current_time_ms=400.0, mempool_utilization=0.5)
        assert fm.base_fee < initial_fee, (
            "First-price model should decay (0.95×) when no fees are recorded. "
            f"initial={initial_fee}, after={fm.base_fee}"
        )
        assert fm.base_fee == pytest.approx(100.0 * 0.95, rel=0.01)


# ---------------------------------------------------------------------------
# Bug 8 — schedule_upload wired (smoke test)
# ---------------------------------------------------------------------------

class TestScheduleUploadWired:
    """Verify schedule_upload is called during NIC-contention propagation."""

    def test_upload_free_at_advances_after_propagation(self):
        """After a block propagates, sender._upload_free_at must be > 0."""
        from simulator.core.engine import DESEngine, SimulationConfig

        cfg = SimulationConfig(
            chain="ethereum",
            signature_algorithm="ECDSA",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=15_000,
            random_seed=42,
            nic_contention_enabled=True,
        )
        engine = DESEngine(cfg)
        result = engine.run()

        # After simulation, at least one node should have uploaded something
        validators = [
            n for n in engine.topology.nodes.values()
            if n.config.is_validator
        ]
        upload_free_ats = [n._upload_free_at for n in validators]
        # At least some nodes should have _upload_free_at > 0 (had sends)
        assert any(t > 0.0 for t in upload_free_ats), (
            "No validator had _upload_free_at > 0 after simulation. "
            "schedule_upload may not be wired correctly."
        )
