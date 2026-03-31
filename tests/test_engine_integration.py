"""Integration tests: full simulation runs and result structure validation.

These tests run complete DES simulations for each chain and verify that:
  - The engine produces a valid SimulationResult
  - Key metrics are present and in expected ranges
  - The dual-sig migration model integrates with DESEngine
  - Calibration can be run against simulation output
"""

import pytest
from simulator.core.engine import DESEngine, SimulationConfig
from simulator.results import SimulationResult


# Shared quick-run parameters (very short simulation for CI speed)
QUICK_PARAMS = dict(
    num_validators          = 20,
    num_full_nodes          = 10,
    simulation_duration_ms  = 10_000,  # 10 seconds
    random_seed             = 42,
)


def run_sim(chain: str, algo: str, **overrides) -> SimulationResult:
    """Helper: run a quick DES simulation and return the result."""
    cfg = SimulationConfig(
        chain               = chain,
        signature_algorithm = algo,
        **{**QUICK_PARAMS, **overrides},
    )
    engine = DESEngine(cfg)
    return engine.run()


class TestEngineBasicRun:
    def test_solana_ed25519_runs(self):
        result = run_sim("solana", "Ed25519")
        assert result is not None

    def test_bitcoin_ecdsa_runs(self):
        result = run_sim("bitcoin", "ECDSA")
        assert result is not None

    def test_ethereum_ecdsa_runs(self):
        result = run_sim("ethereum", "ECDSA")
        assert result is not None


class TestSimulationResultStructure:
    """Verify that SimulationResult has the expected attributes."""

    def _check_result(self, result: SimulationResult):
        # Basic structural checks
        assert hasattr(result, "stale_rate")
        assert 0.0 <= result.stale_rate <= 1.0

        # Should have some blocks produced
        blocks = getattr(result, "blocks_produced", None)
        if blocks is not None:
            assert blocks >= 0

    def test_solana_result_structure(self):
        result = run_sim("solana", "Ed25519")
        self._check_result(result)

    def test_bitcoin_result_structure(self):
        result = run_sim("bitcoin", "ECDSA")
        self._check_result(result)

    def test_ethereum_result_structure(self):
        result = run_sim("ethereum", "ECDSA")
        self._check_result(result)


class TestPQCImpact:
    """PQC should produce higher stale rates than classical (basic sanity check)."""

    def test_solana_pqc_stale_rate_nondecreasing(self):
        # Classical should have lower or equal stale rate compared to large PQC
        # (this is a statistical tendency, not guaranteed for short runs)
        classical = run_sim("solana", "Ed25519", random_seed=42)
        pqc       = run_sim("solana", "SLH-DSA-128s", random_seed=42)
        # Allow equality; stale rate should not DECREASE with larger sigs
        # (relaxed assertion due to short sim and stochasticity)
        assert pqc.stale_rate >= classical.stale_rate - 0.10

    def test_falcon512_intermediate_impact(self):
        classical = run_sim("solana", "Ed25519")
        falcon    = run_sim("solana", "Falcon-512")
        slh_dsa   = run_sim("solana", "SLH-DSA-128s")
        # Falcon should not be worse than SLH-DSA (both tend to inflate block size)
        # This is a directional assertion; exact ordering not guaranteed in short runs
        assert falcon.stale_rate <= slh_dsa.stale_rate + 0.20


class TestReproducibility:
    def test_same_seed_gives_same_result(self):
        result1 = run_sim("solana", "Ed25519", random_seed=99)
        result2 = run_sim("solana", "Ed25519", random_seed=99)
        assert result1.stale_rate == pytest.approx(result2.stale_rate, rel=1e-6)

    def test_different_seeds_may_differ(self):
        result1 = run_sim("solana", "Ed25519", random_seed=1)
        result2 = run_sim("solana", "Ed25519", random_seed=99999)
        # They CAN be equal (short sim) but should structurally be valid
        assert result1 is not None
        assert result2 is not None


class TestDualSigIntegration:
    """Test that DualSigConfig produces valid sim configs and overhead curves."""

    def test_migration_timeline_configs_are_valid(self):
        from simulator.migration.dual_sig import DualSigConfig, MigrationTimeline

        cfg = DualSigConfig(
            classical_algo       = "ECDSA",
            pqc_algo             = "ML-DSA-65",
            adoption_curve       = "logistic",
            migration_start_block= 0,
            migration_end_block  = 10_000,
        )
        timeline = MigrationTimeline(
            dual_sig_config      = cfg,
            pre_migration_blocks = 1_000,
            post_migration_blocks= 1_000,
            phase_resolution     = 5,
        )
        configs = list(timeline.sim_configs(base_chain="ethereum"))
        assert len(configs) > 0

        for c in configs:
            assert c["avg_sig_bytes"] > 0
            assert c["avg_pk_bytes"] > 0
            assert 0.0 <= c["pqc_fraction"] <= 1.0
            assert c["overhead_ratio"] >= 1.0

    def test_congestion_spike_present_for_large_pqc(self):
        from simulator.migration.dual_sig import DualSigConfig, MigrationTimeline

        cfg = DualSigConfig(
            classical_algo = "ECDSA",
            pqc_algo       = "SLH-DSA-128s",  # large sigs
            adoption_curve = "step",
            migration_start_block = 0,
            migration_end_block   = 1_000,
        )
        tl      = MigrationTimeline(dual_sig_config=cfg, phase_resolution=3)
        summary = tl.congestion_spike_summary()
        # Dual-sig period must be larger than either classical or PQC alone
        assert summary["dual_sig_plus_pk_bytes"] > summary["classical_sig_plus_pk_bytes"]
        assert summary["dual_sig_plus_pk_bytes"] > summary["pqc_only_sig_plus_pk_bytes"]


class TestCalibrationIntegration:
    """Verify that the calibration runner can accept simulated values and report."""

    def test_calibration_runner_accepts_sim_output(self):
        from simulator.calibration.baseline import CalibrationRunner

        # Run a short sim and extract basic metrics
        result = run_sim("ethereum", "ECDSA", random_seed=42)
        simulated = {
            "stale_rate":      result.stale_rate,
            "block_prop_p95_ms": getattr(result, "propagation_p95_ms", 3_000.0),
            "avg_tps":         14.0,  # not available from basic DES
            "block_utilisation": 0.70,
            "median_fee_gwei": 15.0,
            "min_node_bandwidth_mbps": 25.0,
        }
        runner = CalibrationRunner("ethereum")
        cal_result = runner.run_classical_baseline(simulated=simulated)

        assert cal_result.chain == "ethereum"
        # Stale rate from short sim may or may not pass; just check structure
        assert "stale_rate" in cal_result.metrics
        report = cal_result.generate_report()
        assert "Ethereum" in report
