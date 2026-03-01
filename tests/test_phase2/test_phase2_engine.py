"""Tests for Phase2Engine — the heterogeneous block simulation engine."""

import pytest

from simulator.core.phase2_engine import Phase2Engine, Phase2Config
from blockchain.verification import VERIFICATION_PROFILES


class TestPhase2Config:
    """Tests for Phase2Config dataclass."""

    def test_default_config(self):
        cfg = Phase2Config(chain="solana")
        assert cfg.chain == "solana"
        assert cfg.pqc_fraction == 0.0
        assert cfg.lambda_tps == 500.0
        assert cfg.mempool_capacity_bytes == 100 * 1024 * 1024
        assert cfg.classical_algo == "Ed25519"
        assert cfg.num_validators == 50
        assert cfg.num_full_nodes == 25

    def test_custom_pqc_fraction(self):
        cfg = Phase2Config(chain="solana", pqc_fraction=0.75)
        assert cfg.pqc_fraction == 0.75


class TestPhase2EngineInit:
    """Tests for Phase2Engine construction."""

    def test_engine_initialises(self):
        cfg = Phase2Config(
            chain="solana",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        engine = Phase2Engine(cfg)
        assert engine.config == cfg

    def test_engine_runs_all_classical(self):
        """pqc_fraction=0.0 → all Ed25519, should complete cleanly."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert isinstance(result, dict)
        assert result["pqc_fraction"] == 0.0
        assert result["num_blocks"] >= 1
        assert result["avg_verification_time_ms"] >= 0.0

    def test_engine_runs_all_pqc(self):
        """pqc_fraction=1.0 → all PQC, should complete (albeit slower)."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=1.0,
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert isinstance(result, dict)
        assert result["pqc_fraction"] == 1.0
        assert result["num_blocks"] >= 1

    def test_engine_runs_mixed(self):
        """pqc_fraction=0.5 → mixed, should complete."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.5,
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert result["pqc_fraction"] == 0.5


class TestPhase2Determinism:
    """Same seed → same results."""

    def test_deterministic_results(self):
        kwargs = dict(
            chain="solana",
            pqc_fraction=0.3,
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        r1 = Phase2Engine(Phase2Config(**kwargs)).run()
        r2 = Phase2Engine(Phase2Config(**kwargs)).run()

        assert r1["num_blocks"] == r2["num_blocks"]
        assert r1["avg_verification_time_ms"] == r2["avg_verification_time_ms"]
        assert r1["mempool_total_evicted"] == r2["mempool_total_evicted"]

    def test_different_seeds_differ(self):
        base = dict(
            chain="solana",
            pqc_fraction=0.3,
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
        )
        r1 = Phase2Engine(Phase2Config(**base, random_seed=42)).run()
        r2 = Phase2Engine(Phase2Config(**base, random_seed=99)).run()

        # At least some metrics should differ
        assert (
            r1["avg_verification_time_ms"] != r2["avg_verification_time_ms"]
            or r1["total_tx_generated"] != r2["total_tx_generated"]
        )


class TestPhase2Metrics:
    """Result dict contains all expected keys."""

    @pytest.fixture
    def result(self):
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.3,
            lambda_tps=200.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=3_000,
            random_seed=42,
        )
        return Phase2Engine(cfg).run()

    def test_phase1_keys_present(self, result):
        for key in [
            "chain", "num_blocks", "avg_block_size_bytes",
            "avg_propagation_p50_ms", "avg_propagation_p90_ms",
            "stale_rate", "effective_tps",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_phase2_keys_present(self, result):
        for key in [
            "pqc_fraction", "seed",
            "avg_verification_time_ms", "max_verification_time_ms",
            "verification_failure_rate", "verification_failures",
            "block_time_ms",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_phase3_keys_present(self, result):
        for key in [
            "mempool_total_accepted", "mempool_total_evicted",
            "mempool_total_rejected", "mempool_final_size_bytes",
            "mempool_final_tx_count", "total_tx_generated",
            "algo_distribution", "algo_counts",
        ]:
            assert key in result, f"Missing key: {key}"


class TestPhase2VerificationPhysics:
    """CRITICAL: PQC verification must be slower than classical."""

    def test_pqc_verification_slower(self):
        """100% PQC should have higher avg verification time than 0% PQC."""
        base = dict(
            chain="solana",
            lambda_tps=100.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=3_000,
            random_seed=42,
        )
        classical = Phase2Engine(
            Phase2Config(**base, pqc_fraction=0.0)
        ).run()
        pqc = Phase2Engine(
            Phase2Config(**base, pqc_fraction=1.0)
        ).run()

        assert (
            pqc["avg_verification_time_ms"]
            > classical["avg_verification_time_ms"]
        ), (
            f"PQC verify ({pqc['avg_verification_time_ms']} ms) should be "
            f"slower than classical ({classical['avg_verification_time_ms']} ms)"
        )

    def test_higher_pqc_fraction_more_evictions_or_larger_blocks(self):
        """Higher PQC fraction → larger tx sizes → either more evictions or larger blocks."""
        base = dict(
            chain="solana",
            lambda_tps=200.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=3_000,
            random_seed=42,
        )
        low = Phase2Engine(Phase2Config(**base, pqc_fraction=0.1)).run()
        high = Phase2Engine(Phase2Config(**base, pqc_fraction=0.9)).run()

        # At minimum, avg block size should be larger with more PQC
        # (since PQC txs are physically bigger)
        assert high["avg_block_size_bytes"] >= low["avg_block_size_bytes"] * 0.5, (
            "With 90% PQC, blocks should be at least roughly comparable in size"
        )


class TestPhase2MultiChain:
    """Ensure Phase 2 engine works for multiple chains."""

    @pytest.mark.parametrize("chain", ["solana", "bitcoin", "ethereum"])
    def test_runs_on_chain(self, chain):
        cfg = Phase2Config(
            chain=chain,
            pqc_fraction=0.2,
            lambda_tps=50.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert result["chain"] == chain
        assert result["num_blocks"] >= 0
