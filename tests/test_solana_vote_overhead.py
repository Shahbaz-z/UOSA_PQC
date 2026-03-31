"""Tests for simulator/chains/solana_specific.py.

Covers SolanaTxModel vote saturation detection, capacity analysis,
compute unit limits, and Gulf Stream prefetch overhead.
"""

import pytest
from simulator.chains.solana_specific import (
    SolanaTxModel,
    VOTE_TX_FRACTION,
    VOTE_TX_ED25519_SIZE,
    BLOCK_SIZE_BYTES,
    BLOCK_COMPUTE_UNIT_LIMIT,
    CU_COSTS,
    DEFAULT_SOLANA_TX_MODEL,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


class TestVoteTxSize:
    def test_ed25519_matches_constant(self):
        model = SolanaTxModel()
        size = model.vote_tx_size("Ed25519")
        assert size == pytest.approx(VOTE_TX_ED25519_SIZE, abs=20)

    def test_mldsa65_larger_than_ed25519(self):
        model = SolanaTxModel()
        assert model.vote_tx_size("ML-DSA-65") > model.vote_tx_size("Ed25519")

    def test_falcon512_larger_than_ed25519(self):
        model = SolanaTxModel()
        assert model.vote_tx_size("Falcon-512") > model.vote_tx_size("Ed25519")

    def test_size_reflects_signature_size(self):
        model = SolanaTxModel()
        for algo in ["ML-DSA-65", "Falcon-512", "SLH-DSA-128s"]:
            size = model.vote_tx_size(algo)
            expected_min = SIGNATURE_SIZES.get(algo, 0) + PUBLIC_KEY_SIZES.get(algo, 0)
            assert size > expected_min


class TestUserTxSize:
    def test_ed25519_tx_is_small(self):
        model = SolanaTxModel()
        size = model.user_tx_size("Ed25519")
        assert size < 500

    def test_pqc_tx_larger_than_classical(self):
        model = SolanaTxModel()
        ed_size  = model.user_tx_size("Ed25519")
        pqc_size = model.user_tx_size("ML-DSA-65")
        assert pqc_size > ed_size

    def test_calldata_increases_size(self):
        model = SolanaTxModel()
        small = model.user_tx_size("Ed25519", calldata_bytes=0)
        large = model.user_tx_size("Ed25519", calldata_bytes=500)
        assert large > small


class TestBlockCapacityAnalysis:
    def test_ed25519_not_saturated(self):
        model = SolanaTxModel(validators_per_slot=1500)
        cap = model.block_capacity_analysis("Ed25519")
        assert cap["is_vote_saturated"] is False

    def test_slh_dsa_128s_may_saturate(self):
        # SLH-DSA-128s has massive signatures; with 1500 validators it will overflow
        model = SolanaTxModel(validators_per_slot=1500)
        cap = model.block_capacity_analysis("SLH-DSA-128s")
        # Either vote-saturated or extremely small user capacity
        assert cap["is_vote_saturated"] or cap["user_tx_capacity_bytes"] < 500_000

    def test_returns_all_keys(self):
        model = SolanaTxModel()
        cap = model.block_capacity_analysis("Ed25519")
        required_keys = [
            "vote_tx_size_bytes", "vote_tx_count", "vote_tx_bytes_total",
            "user_tx_capacity_bytes", "max_user_txs", "vote_overhead_ratio",
            "is_vote_saturated", "compute_unit_total_votes", "is_cu_saturated",
        ]
        for key in required_keys:
            assert key in cap, f"Missing key: {key}"

    def test_vote_overhead_ratio_between_0_and_1_for_ed25519(self):
        model = SolanaTxModel(validators_per_slot=1500)
        cap = model.block_capacity_analysis("Ed25519")
        assert 0.0 < cap["vote_overhead_ratio"] <= 1.0

    def test_user_capacity_plus_vote_equals_block_size_or_overflow(self):
        model = SolanaTxModel(validators_per_slot=100)
        cap = model.block_capacity_analysis("ML-DSA-65")
        if not cap["is_vote_saturated"]:
            total = cap["vote_tx_bytes_total"] + cap["user_tx_capacity_bytes"]
            assert total == pytest.approx(model.block_size_bytes, abs=100)

    def test_cu_saturation_for_slh_dsa_128s_small_validators(self):
        # Even with few validators, SLH-DSA-128s CUs may hit the limit
        model = SolanaTxModel(validators_per_slot=100)
        cap = model.block_capacity_analysis("SLH-DSA-128s")
        # 100 validators × 40,000 CU = 4M < 48M → should NOT be CU saturated
        assert cap["is_cu_saturated"] is False

    def test_cu_saturation_triggers_with_many_validators(self):
        # SLH-DSA-128s: 40,000 CU × 1500 validators = 60M > 48M CU limit
        model = SolanaTxModel(validators_per_slot=1500)
        cap = model.block_capacity_analysis("SLH-DSA-128s")
        assert cap["is_cu_saturated"] is True


class TestComputeUnitCost:
    def test_ed25519_is_low(self):
        model = SolanaTxModel()
        assert model.compute_unit_cost("Ed25519") < 500

    def test_pqc_is_higher_than_classical(self):
        model = SolanaTxModel()
        ed_cu   = model.compute_unit_cost("Ed25519")
        pqc_cu  = model.compute_unit_cost("ML-DSA-65")
        assert pqc_cu > ed_cu

    def test_slh_dsa_is_most_expensive(self):
        model = SolanaTxModel()
        slh_cu    = model.compute_unit_cost("SLH-DSA-128s")
        falcon_cu = model.compute_unit_cost("Falcon-512")
        assert slh_cu > falcon_cu


class TestGulfStreamPrefetch:
    def test_ed25519_baseline(self):
        model = SolanaTxModel()
        overhead = model.gulf_stream_prefetch_overhead("Ed25519", pending_txs=1000)
        assert overhead["bandwidth_vs_ed25519_ratio"] == pytest.approx(1.0, rel=0.05)

    def test_pqc_increases_bandwidth(self):
        model = SolanaTxModel()
        overhead = model.gulf_stream_prefetch_overhead("ML-DSA-65", pending_txs=1000)
        assert overhead["bandwidth_vs_ed25519_ratio"] > 1.0

    def test_overhead_scales_with_pending_txs(self):
        model = SolanaTxModel()
        small = model.gulf_stream_prefetch_overhead("ML-DSA-65", pending_txs=100)
        large = model.gulf_stream_prefetch_overhead("ML-DSA-65", pending_txs=1000)
        assert large["total_forwarded_bytes"] == 10 * small["total_forwarded_bytes"]


class TestMigrationCapacityCurve:
    def test_curve_has_correct_length(self):
        model = SolanaTxModel()
        curve = model.migration_capacity_curve("ML-DSA-65", pqc_fractions=[0.0, 0.5, 1.0])
        assert len(curve) == 3

    def test_zero_fraction_matches_ed25519(self):
        model = SolanaTxModel()
        curve = model.migration_capacity_curve("ML-DSA-65", pqc_fractions=[0.0])
        # At 0% PQC, avg vote size should match Ed25519 vote size
        assert curve[0]["avg_vote_tx_size_bytes"] == pytest.approx(
            model.vote_tx_size("Ed25519"), rel=0.01
        )

    def test_one_fraction_matches_pqc(self):
        model = SolanaTxModel()
        curve = model.migration_capacity_curve("ML-DSA-65", pqc_fractions=[1.0])
        assert curve[0]["avg_vote_tx_size_bytes"] == pytest.approx(
            model.vote_tx_size("ML-DSA-65"), rel=0.01
        )

    def test_overhead_increases_with_pqc_fraction(self):
        model = SolanaTxModel()
        curve = model.migration_capacity_curve("ML-DSA-65", pqc_fractions=[0.0, 0.5, 1.0])
        vote_bytes = [c["vote_bytes_total"] for c in curve]
        assert vote_bytes[0] <= vote_bytes[1] <= vote_bytes[2]
