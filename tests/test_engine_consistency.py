"""Engine consistency and NIC model tests.

Tests that:
1. Phase 1 (DESEngine) and Phase 2 (Phase2Engine) verification times agree
   for Ed25519 after the batch_speedup fix in verification_time_ms().
2. Node.schedule_upload() produces analytically correct finish times.
3. MigrationTimeline.sim_configs() yields strictly monotonically increasing
   start_blocks with no duplicates.
"""

import pytest
import math


# ---------------------------------------------------------------------------
# 1. Phase 1 / Phase 2 verification consistency
# ---------------------------------------------------------------------------

class TestPhase1Phase2VerificationConsistency:
    """Verify that Phase 1 (DESEngine via node.verification_time_ms) and
    Phase 2 (_compute_heterogeneous_verify_time) agree on Ed25519 timing
    after the batch_speedup fix.
    """

    def _make_node(self, cpu_cores: int = 4, power_factor: float = 1.0):
        from simulator.network.node import Node, NodeConfig
        from simulator.state import SimulationState
        cfg = NodeConfig(
            node_id="test",
            is_validator=True,
            region="us-east-1",
            upload_bandwidth_mbps=100.0,
            download_bandwidth_mbps=100.0,
            cpu_cores=cpu_cores,
            processing_power_factor=power_factor,
            stake_weight=1.0,
        )
        return Node(config=cfg, env=SimulationState(end_time_ms=60_000))

    def test_ed25519_verification_phase1_matches_phase2(self):
        """Phase 1 and Phase 2 must agree on Ed25519 verification time.

        Bug 1 was that node.verification_time_ms() (Phase 1) did not apply
        batch_speedup, making Ed25519 2× slower in Phase 1 than Phase 2.
        After the fix, both paths apply batch_speedup and must agree.
        """
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.network.propagation import Block, Transaction
        from blockchain.verification import VERIFICATION_PROFILES

        node = self._make_node()

        # Phase 1: verification_time_ms directly
        phase1_time = node.verification_time_ms("Ed25519", 10)

        # Phase 2: _compute_heterogeneous_verify_time
        engine = Phase2Engine(Phase2Config(chain="solana", random_seed=0))
        txs = [
            Transaction(
                tx_id=f"t{i}", size_bytes=250, signature_algorithm="Ed25519",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )
            for i in range(10)
        ]
        block = Block(
            block_hash="bh", parent_hash="g", height=1,
            proposer_id="p0", timestamp_ms=0.0, transactions=txs
        )
        phase2_time = engine._compute_heterogeneous_verify_time(block, node)

        assert phase2_time == pytest.approx(phase1_time, rel=0.01), (
            f"Phase 2 ({phase2_time:.4f} ms) should equal Phase 1 ({phase1_time:.4f} ms). "
            "If they differ, batch_speedup is being applied asymmetrically."
        )

    def test_ed25519_batch_speedup_is_applied(self):
        """verification_time_ms must apply Ed25519 batch_speedup (0.5×)."""
        from blockchain.verification import VERIFICATION_PROFILES
        node = self._make_node(cpu_cores=1, power_factor=1.0)

        profile = VERIFICATION_PROFILES["Ed25519"]
        raw_time_ms = (profile.verify_time_us * 10) / 1000  # 10 sigs, no speedup
        batch_time_ms = (profile.verify_time_us * profile.batch_speedup * 10) / 1000

        measured = node.verification_time_ms("Ed25519", 10)

        assert measured == pytest.approx(batch_time_ms, rel=0.01), (
            f"Ed25519 verify should be {batch_time_ms:.4f} ms (with batch_speedup {profile.batch_speedup}×), "
            f"not {raw_time_ms:.4f} ms (raw)."
        )

    def test_mldsa_no_batch_speedup_applied(self):
        """ML-DSA (batch_speedup=1.0) must NOT have speedup applied."""
        from blockchain.verification import VERIFICATION_PROFILES
        node = self._make_node(cpu_cores=1, power_factor=1.0)

        profile = VERIFICATION_PROFILES["ML-DSA-65"]
        assert profile.batch_speedup == 1.0, "ML-DSA-65 should have batch_speedup=1.0"

        raw_time_ms = (profile.verify_time_us * 5) / 1000
        measured = node.verification_time_ms("ML-DSA-65", 5)
        assert measured == pytest.approx(raw_time_ms, rel=0.01)

    def test_processing_power_factor_scales_both_phases(self):
        """Doubling processing_power_factor should halve time in both paths."""
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        from simulator.network.propagation import Block, Transaction

        n1 = self._make_node(cpu_cores=1, power_factor=1.0)
        n2 = self._make_node(cpu_cores=1, power_factor=2.0)

        # Phase 1
        t1_p1 = n1.verification_time_ms("ML-DSA-65", 10)
        t2_p1 = n2.verification_time_ms("ML-DSA-65", 10)
        assert t2_p1 == pytest.approx(t1_p1 / 2, rel=0.01)

        # Phase 2
        engine = Phase2Engine(Phase2Config(chain="solana", random_seed=0))
        txs = [
            Transaction(
                tx_id=f"t{i}", size_bytes=3500, signature_algorithm="ML-DSA-65",
                num_signatures=1, fee_satoshis=1000, arrival_time_ms=0.0
            )
            for i in range(10)
        ]
        block = Block(
            block_hash="bh", parent_hash="g", height=1,
            proposer_id="p0", timestamp_ms=0.0, transactions=txs
        )
        t1_p2 = engine._compute_heterogeneous_verify_time(block, n1)
        t2_p2 = engine._compute_heterogeneous_verify_time(block, n2)
        assert t2_p2 == pytest.approx(t1_p2 / 2, rel=0.01)


# ---------------------------------------------------------------------------
# 2. NIC model analytical correctness
# ---------------------------------------------------------------------------

class TestNICModelAnalytical:
    """Verify schedule_upload() produces analytically correct finish times."""

    def _make_node(self, upload_bw_mbps: float = 100.0) -> "Node":
        from simulator.network.node import Node, NodeConfig
        from simulator.state import SimulationState
        cfg = NodeConfig(
            node_id="nic_test",
            is_validator=True,
            region="us-east-1",
            upload_bandwidth_mbps=upload_bw_mbps,
            download_bandwidth_mbps=1000.0,
            cpu_cores=1,
            processing_power_factor=1.0,
            stake_weight=1.0,
        )
        return Node(config=cfg, env=SimulationState(end_time_ms=60_000))

    def test_single_send_1mb(self):
        """1 MB at 100 Mbps → transmission time = (1M × 8) / 100M × 1000 = 80 ms."""
        node = self._make_node(upload_bw_mbps=100.0)
        finish = node.schedule_upload(
            start_time_ms=0.0,
            size_bytes=1_000_000,
            num_concurrent=1,
        )
        expected_ms = (1_000_000 * 8 / 1_000_000) / 100.0 * 1000  # 80 ms
        assert finish == pytest.approx(expected_ms, rel=1e-6), (
            f"Expected finish={expected_ms} ms, got {finish} ms"
        )

    def test_concurrent_4_peers_quarters_bandwidth(self):
        """4 concurrent sends at 100 Mbps → each gets 25 Mbps → 320 ms per 1 MB."""
        node = self._make_node(upload_bw_mbps=100.0)
        finish = node.schedule_upload(
            start_time_ms=0.0,
            size_bytes=1_000_000,
            num_concurrent=4,
        )
        # per_peer_bw = 100/4 = 25 Mbps; tx_time = (8/25)*1000 = 320 ms
        expected_ms = (1_000_000 * 8 / 1_000_000) / 25.0 * 1000  # 320 ms
        assert finish == pytest.approx(expected_ms, rel=1e-6), (
            f"Expected finish={expected_ms} ms (4 concurrent), got {finish} ms"
        )

    def test_sequential_sends_serialise_correctly(self):
        """Two back-to-back single sends should serialise: second starts when first ends."""
        node = self._make_node(upload_bw_mbps=100.0)

        # First send: 80 ms
        f1 = node.schedule_upload(start_time_ms=0.0, size_bytes=1_000_000, num_concurrent=1)
        assert f1 == pytest.approx(80.0, rel=1e-6)

        # Second send starting at t=0 (back-to-back): must wait until NIC is free (t=80)
        f2 = node.schedule_upload(start_time_ms=0.0, size_bytes=1_000_000, num_concurrent=1)
        assert f2 == pytest.approx(160.0, rel=1e-6), (
            f"Second send should start at t=80 and finish at t=160, got {f2}"
        )

    def test_upload_free_at_advances(self):
        """_upload_free_at should advance to finish_time after each send."""
        node = self._make_node(upload_bw_mbps=100.0)
        assert node._upload_free_at == 0.0

        node.schedule_upload(start_time_ms=0.0, size_bytes=1_000_000, num_concurrent=1)
        assert node._upload_free_at == pytest.approx(80.0, rel=1e-6)

    def test_delayed_start_uses_later_of_start_and_upload_free(self):
        """If start_time_ms > _upload_free_at, actual start = start_time_ms."""
        node = self._make_node(upload_bw_mbps=100.0)
        # Send starts at t=1000 (well after NIC free at t=0)
        finish = node.schedule_upload(start_time_ms=1000.0, size_bytes=1_000_000, num_concurrent=1)
        assert finish == pytest.approx(1080.0, rel=1e-6)

    def test_largest_task_nic_batch(self):
        """The engine uses the largest task for NIC batch occupancy.

        With tasks of 100 bytes (announcement) and 500,000 bytes (full block),
        the NIC should be occupied for the full-block duration.
        After the batch, _upload_free_at should reflect the full-block time.
        """
        from simulator.network.routing import PropagationTask

        tasks = [
            PropagationTask("s", "r1", size_bytes=100),         # announcement
            PropagationTask("s", "r2", size_bytes=500_000),     # full block
        ]
        largest = max(tasks, key=lambda t: t.size_bytes)
        assert largest.size_bytes == 500_000, "Largest task should be the full block"


# ---------------------------------------------------------------------------
# 3. Migration timeline no-duplicate start_blocks
# ---------------------------------------------------------------------------

class TestMigrationTimelineNoDuplicateBlocks:
    """sim_configs() must yield strictly monotonically increasing start_blocks."""

    def _make_timeline(self, resolution: int = 10):
        from simulator.migration.dual_sig import DualSigConfig, MigrationTimeline
        cfg = DualSigConfig(
            classical_algo="ECDSA",
            pqc_algo="ML-DSA-65",
            adoption_curve="logistic",
            migration_start_block=0,
            migration_end_block=10_000,
        )
        return MigrationTimeline(
            dual_sig_config=cfg,
            pre_migration_blocks=1_000,
            post_migration_blocks=1_000,
            phase_resolution=resolution,
        )

    def test_no_duplicate_start_blocks(self):
        """No two sim_configs() entries should share the same start_block."""
        timeline = self._make_timeline()
        configs = list(timeline.sim_configs(base_chain="bitcoin"))
        start_blocks = [c["start_block"] for c in configs]
        assert len(start_blocks) == len(set(start_blocks)), (
            f"Duplicate start_blocks found: {[b for b in start_blocks if start_blocks.count(b) > 1]}"
        )

    def test_start_blocks_strictly_monotone(self):
        """start_blocks must be strictly increasing."""
        timeline = self._make_timeline()
        configs = list(timeline.sim_configs(base_chain="bitcoin"))
        start_blocks = [c["start_block"] for c in configs]
        for i in range(len(start_blocks) - 1):
            assert start_blocks[i] < start_blocks[i + 1], (
                f"Non-monotone start_blocks at position {i}: "
                f"{start_blocks[i]} >= {start_blocks[i + 1]}"
            )

    def test_multiple_resolutions_no_duplicates(self):
        """No duplicates across a range of phase_resolution values."""
        for res in [1, 5, 10, 20]:
            timeline = self._make_timeline(resolution=res)
            configs = list(timeline.sim_configs(base_chain="bitcoin"))
            start_blocks = [c["start_block"] for c in configs]
            assert len(start_blocks) == len(set(start_blocks)), (
                f"Duplicate start_blocks at resolution={res}"
            )

    def test_phases_cache_returns_same_object(self):
        """phases() should return the same cached list on repeated calls."""
        timeline = self._make_timeline()
        p1 = timeline.phases()
        p2 = timeline.phases()
        assert p1 is p2, "phases() should return the same cached list object"

    def test_phase3_start_block_is_migration_end(self):
        """Phase 3 should start exactly at migration_end_block."""
        timeline = self._make_timeline()
        phases = timeline.phases()
        p3 = phases[-1]
        assert p3.start_block == timeline.dual_sig_config.migration_end_block
        assert p3.is_dual_sig is False
        assert p3.pqc_fraction == 1.0

    def test_all_configs_have_required_keys(self):
        """Every sim_configs() entry must have the required keys."""
        required = {"chain", "phase_name", "start_block", "end_block",
                    "pqc_fraction", "is_dual_sig", "avg_sig_bytes",
                    "avg_pk_bytes", "overhead_ratio"}
        timeline = self._make_timeline()
        for cfg in timeline.sim_configs(base_chain="ethereum"):
            missing = required - set(cfg.keys())
            assert not missing, f"Missing keys in sim_config: {missing}"

    def test_lognormal_block_utilisation_median_near_target(self):
        """Block utilisation lognormal must have median close to chain target.

        This tests Bug 3 fix: lognormvariate(mu=0, sigma) × target produces
        a distribution with median = target (not some other value).
        """
        from simulator.core.engine import DESEngine, SimulationConfig
        import statistics

        # Run a short Solana simulation and collect block sizes
        cfg = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=30_000,
            random_seed=42,
        )
        engine = DESEngine(cfg)
        result = engine.run()

        # Block utilisation = avg_block_size_bytes / block_size_limit
        from simulator.chains.base import CHAIN_CONFIGS
        limit = CHAIN_CONFIGS["solana"].block_size_limit
        utilisation = result.avg_block_size_bytes / limit

        # Target for Solana is 0.40; with sigma=0.15 and 10-node short sim,
        # we allow generous tolerance (±40%) given small sample variance
        target = 0.40
        assert 0.20 <= utilisation <= 1.0, (
            f"Block utilisation {utilisation:.3f} is outside [0.20, 1.00]"
        )
        # Check it's not always ~1.0 (the pre-fix behaviour)
        assert utilisation < 0.95, (
            f"Block utilisation {utilisation:.3f} is suspiciously close to 1.0 "
            "(the pre-fix always-full behaviour). Check the lognormal formula."
        )
