"""Tests for simulator/migration/dual_sig.py.

Covers DualSigConfig adoption curves, effective sig sizes, MigrationTimeline
phase generation, and congestion spike summary.
"""

import pytest
from simulator.migration.dual_sig import (
    DualSigConfig,
    MigrationTimeline,
    bitcoin_ecdsa_to_falcon512,
    ethereum_ecdsa_to_mldsa65,
    solana_ed25519_to_falcon512,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


class TestDualSigConfig:
    def test_default_construction(self):
        cfg = DualSigConfig()
        assert cfg.classical_algo == "ECDSA"
        assert cfg.pqc_algo == "ML-DSA-65"

    def test_invalid_adoption_curve_raises(self):
        with pytest.raises(ValueError, match="adoption_curve"):
            DualSigConfig(adoption_curve="invalid")

    def test_migration_end_before_start_raises(self):
        with pytest.raises(ValueError):
            DualSigConfig(migration_start_block=1000, migration_end_block=500)

    def test_combined_sig_size_is_sum(self):
        cfg = DualSigConfig(classical_algo="ECDSA", pqc_algo="ML-DSA-65")
        expected = SIGNATURE_SIZES["ECDSA"] + SIGNATURE_SIZES["ML-DSA-65"]
        assert cfg.combined_sig_size() == expected

    def test_combined_pk_size_is_sum(self):
        cfg = DualSigConfig(classical_algo="ECDSA", pqc_algo="Falcon-512")
        expected = PUBLIC_KEY_SIZES["ECDSA"] + PUBLIC_KEY_SIZES["Falcon-512"]
        assert cfg.combined_pk_size() == expected

    def test_adoption_fraction_before_migration_is_zero(self):
        cfg = DualSigConfig(migration_start_block=1000, migration_end_block=2000)
        assert cfg.adoption_fraction(999) == 0.0

    def test_adoption_fraction_after_migration_is_one(self):
        cfg = DualSigConfig(migration_start_block=1000, migration_end_block=2000)
        assert cfg.adoption_fraction(2001) == 1.0

    def test_linear_curve_midpoint_is_half(self):
        cfg = DualSigConfig(
            adoption_curve="linear",
            migration_start_block=0,
            migration_end_block=1000,
        )
        assert cfg.adoption_fraction(500) == pytest.approx(0.5, abs=0.01)

    def test_step_curve_is_one_after_start(self):
        cfg = DualSigConfig(
            adoption_curve="step",
            migration_start_block=500,
            migration_end_block=1500,
        )
        assert cfg.adoption_fraction(501) == 1.0

    def test_logistic_curve_increases_monotonically(self):
        cfg = DualSigConfig(
            adoption_curve="logistic",
            migration_start_block=0,
            migration_end_block=10_000,
        )
        fracs = [cfg.adoption_fraction(b) for b in range(0, 10_001, 500)]
        for i in range(len(fracs) - 1):
            assert fracs[i] <= fracs[i + 1] + 1e-9

    def test_effective_sig_size_at_zero_is_classical(self):
        cfg = DualSigConfig(
            migration_start_block=1000,
            migration_end_block=2000,
        )
        # Before migration, effective sig = classical only
        eff = cfg.effective_avg_sig_size(0)
        assert eff == pytest.approx(float(cfg.classical_sig_size()))

    def test_effective_sig_size_at_end_is_combined(self):
        # At adoption_fraction=1.0 (all txs in dual-sig window), every tx
        # carries both classical + PQC sig → effective = combined_sig_size
        # (Phase 3 drop of classical sig is handled by MigrationTimeline)
        cfg = DualSigConfig(
            migration_start_block=0,
            migration_end_block=1000,
        )
        eff = cfg.effective_avg_sig_size(1001)
        assert eff == pytest.approx(float(cfg.combined_sig_size()))

    def test_effective_sig_size_peak_is_combined(self):
        cfg = DualSigConfig(
            adoption_curve="step",
            migration_start_block=0,
            migration_end_block=1000,
        )
        # With step curve at block 1, adoption = 1.0 → combined sig
        eff = cfg.effective_avg_sig_size(1)
        assert eff == pytest.approx(float(cfg.combined_sig_size()))

    def test_size_overhead_ratio_before_migration_is_one(self):
        cfg = DualSigConfig(migration_start_block=1000, migration_end_block=2000)
        ratio = cfg.size_overhead_ratio(0)
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_size_overhead_ratio_peak_greater_than_one(self):
        cfg = DualSigConfig(
            adoption_curve="step",
            migration_start_block=0,
            migration_end_block=10_000,
        )
        ratio = cfg.size_overhead_ratio(1)
        assert ratio > 1.0


class TestMigrationTimeline:
    def setup_method(self):
        self.cfg = DualSigConfig(
            classical_algo       = "ECDSA",
            pqc_algo             = "ML-DSA-65",
            adoption_curve       = "logistic",
            migration_start_block= 0,
            migration_end_block  = 50_000,
        )
        self.timeline = MigrationTimeline(
            dual_sig_config       = self.cfg,
            pre_migration_blocks  = 5_000,
            post_migration_blocks = 5_000,
            phase_resolution      = 10,
        )

    def test_phases_not_empty(self):
        phases = self.timeline.phases()
        assert len(phases) > 0

    def test_phase1_is_classical(self):
        phases = self.timeline.phases()
        phase1 = phases[0]
        assert phase1.is_dual_sig is False
        assert phase1.pqc_fraction == 0.0

    def test_last_phase_is_pqc_only(self):
        phases = self.timeline.phases()
        last = phases[-1]
        assert last.is_dual_sig is False
        assert last.pqc_fraction == 1.0

    def test_dual_sig_phases_present(self):
        phases = self.timeline.phases()
        dual_phases = [p for p in phases if p.is_dual_sig]
        assert len(dual_phases) == self.timeline.phase_resolution

    def test_peak_overhead_phase_has_large_sig(self):
        # The phase with max sig_bytes is either the last dual-sig checkpoint
        # or Phase 3 (PQC-only). Either way it should have larger sigs than
        # the classical Phase 1 baseline.
        peak = self.timeline.peak_overhead_phase()
        classical_phase = self.timeline.phases()[0]
        assert peak.avg_sig_bytes > classical_phase.avg_sig_bytes

    def test_congestion_spike_summary_keys(self):
        summary = self.timeline.congestion_spike_summary()
        required = [
            "classical_sig_plus_pk_bytes",
            "dual_sig_plus_pk_bytes",
            "pqc_only_sig_plus_pk_bytes",
            "peak_overhead_ratio",
            "pqc_overhead_ratio",
        ]
        for key in required:
            assert key in summary, f"Missing key: {key}"

    def test_dual_sig_bytes_greater_than_classical(self):
        summary = self.timeline.congestion_spike_summary()
        assert summary["dual_sig_plus_pk_bytes"] > summary["classical_sig_plus_pk_bytes"]

    def test_pqc_bytes_greater_than_classical(self):
        summary = self.timeline.congestion_spike_summary()
        assert summary["pqc_only_sig_plus_pk_bytes"] > summary["classical_sig_plus_pk_bytes"]

    def test_sim_configs_yields_dicts(self):
        configs = list(self.timeline.sim_configs(base_chain="bitcoin"))
        assert len(configs) > 0
        for c in configs:
            assert "chain" in c
            assert "avg_sig_bytes" in c
            assert "overhead_ratio" in c

    def test_overhead_ratio_increases_through_migration(self):
        # Dual-sig phase should always have higher overhead than Phase 1 (classical)
        configs = list(self.timeline.sim_configs(base_chain="bitcoin"))
        classical_configs = [c for c in configs if not c["is_dual_sig"] and c["pqc_fraction"] == 0.0]
        dual_configs      = [c for c in configs if c["is_dual_sig"]]
        if classical_configs and dual_configs:
            max_dual    = max(c["overhead_ratio"] for c in dual_configs)
            classical   = classical_configs[0]["overhead_ratio"]
            # Dual-sig period must be more expensive than pure classical
            assert max_dual > classical


class TestConvenienceFactories:
    def test_bitcoin_factory(self):
        tl = bitcoin_ecdsa_to_falcon512()
        assert tl.dual_sig_config.classical_algo == "ECDSA"
        assert tl.dual_sig_config.pqc_algo == "Falcon-512"
        assert len(tl.phases()) > 0

    def test_ethereum_factory(self):
        tl = ethereum_ecdsa_to_mldsa65()
        assert tl.dual_sig_config.pqc_algo == "ML-DSA-65"
        summary = tl.congestion_spike_summary()
        assert summary["peak_overhead_ratio"] > 1.0

    def test_solana_factory(self):
        tl = solana_ed25519_to_falcon512()
        assert tl.dual_sig_config.classical_algo == "Ed25519"
        phases = tl.phases()
        assert any(p.is_dual_sig for p in phases)

    def test_cross_chain_consistency(self):
        btc = bitcoin_ecdsa_to_falcon512().congestion_spike_summary()
        eth = ethereum_ecdsa_to_mldsa65().congestion_spike_summary()
        # ML-DSA-65 (Ethereum) has larger dual-sig overhead than Falcon-512 (Bitcoin)
        assert eth["dual_sig_plus_pk_bytes"] > btc["dual_sig_plus_pk_bytes"]
