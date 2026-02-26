"""Tests for blockchain/verification.py -- signature verification time modeling."""

import pytest

from blockchain.verification import (
    VERIFICATION_PROFILES,
    VerificationProfile,
    VerificationResult,
    get_verification_profile,
    compute_block_verification_time,
    compute_verification_limited_tps,
)
from blockchain.chain_models import SIGNATURE_SIZES


# ---------------------------------------------------------------------------
# Profile catalog tests
# ---------------------------------------------------------------------------

class TestVerificationProfiles:
    def test_all_signature_algorithms_have_profiles(self):
        """Every algorithm in SIGNATURE_SIZES should have a verification profile."""
        for algo in SIGNATURE_SIZES:
            assert algo in VERIFICATION_PROFILES, f"Missing profile for {algo}"

    def test_profiles_are_frozen(self):
        """Profiles should be immutable."""
        profile = VERIFICATION_PROFILES["Ed25519"]
        with pytest.raises(AttributeError):
            profile.verify_time_us = 999

    def test_classical_faster_than_pqc(self):
        """Classical algorithms should generally verify faster than PQC."""
        ed = VERIFICATION_PROFILES["Ed25519"].verify_time_us
        falcon = VERIFICATION_PROFILES["Falcon-512"].verify_time_us
        mldsa = VERIFICATION_PROFILES["ML-DSA-65"].verify_time_us
        assert ed < falcon < mldsa

    def test_falcon_faster_than_mldsa(self):
        """Falcon verification should be faster than ML-DSA at same security level."""
        assert VERIFICATION_PROFILES["Falcon-512"].verify_time_us < VERIFICATION_PROFILES["ML-DSA-44"].verify_time_us

    def test_slh_dsa_slow_variants(self):
        """SLH-DSA 's' variants should be slower than 'f' variants."""
        assert VERIFICATION_PROFILES["SLH-DSA-128s"].verify_time_us > VERIFICATION_PROFILES["SLH-DSA-128f"].verify_time_us
        assert VERIFICATION_PROFILES["SLH-DSA-256s"].verify_time_us > VERIFICATION_PROFILES["SLH-DSA-256f"].verify_time_us

    def test_hybrid_is_sum(self):
        """Hybrid verification time should be sum of both components."""
        ed_time = VERIFICATION_PROFILES["Ed25519"].verify_time_us
        falcon_time = VERIFICATION_PROFILES["Falcon-512"].verify_time_us
        hybrid_time = VERIFICATION_PROFILES["Hybrid-Ed25519+Falcon-512"].verify_time_us
        assert hybrid_time == ed_time + falcon_time

    def test_all_verify_times_positive(self):
        for algo, profile in VERIFICATION_PROFILES.items():
            assert profile.verify_time_us > 0, f"{algo} has non-positive verify time"

    def test_batch_speedup_range(self):
        for algo, profile in VERIFICATION_PROFILES.items():
            assert 0 < profile.batch_speedup <= 1.0, f"{algo} batch_speedup out of range: {profile.batch_speedup}"

    def test_ed25519_batch_speedup(self):
        """Ed25519 supports batch verification (speedup < 1.0)."""
        assert VERIFICATION_PROFILES["Ed25519"].batch_speedup < 1.0

    def test_schnorr_batch_speedup(self):
        """Schnorr supports batch verification (MuSig-style)."""
        assert VERIFICATION_PROFILES["Schnorr"].batch_speedup < 1.0


# ---------------------------------------------------------------------------
# get_verification_profile tests
# ---------------------------------------------------------------------------

class TestGetVerificationProfile:
    def test_valid_algorithm(self):
        profile = get_verification_profile("Falcon-512")
        assert isinstance(profile, VerificationProfile)
        assert profile.algorithm == "Falcon-512"

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError, match="Unknown algorithm"):
            get_verification_profile("NotAnAlgorithm")


# ---------------------------------------------------------------------------
# Block verification time tests
# ---------------------------------------------------------------------------

class TestComputeBlockVerificationTime:
    def test_basic_result(self):
        result = compute_block_verification_time(
            "Ed25519", txs_per_block=1000, block_time_ms=400.0, num_cores=4
        )
        assert isinstance(result, VerificationResult)
        assert result.algorithm == "Ed25519"
        assert result.txs_in_block == 1000
        assert result.num_cores == 4

    def test_serial_time_calculation(self):
        """Serial time = verify_time_us * num_txs / 1000."""
        result = compute_block_verification_time(
            "Ed25519", txs_per_block=1000, block_time_ms=400.0, num_cores=1,
            use_batch=False,
        )
        expected_ms = 60.0 * 1000 / 1000.0  # 60ms
        assert result.serial_time_ms == expected_ms

    def test_parallel_speedup(self):
        """4 cores should give ~4x speedup."""
        result_1 = compute_block_verification_time(
            "ML-DSA-65", txs_per_block=500, block_time_ms=12000.0, num_cores=1,
            use_batch=False,
        )
        result_4 = compute_block_verification_time(
            "ML-DSA-65", txs_per_block=500, block_time_ms=12000.0, num_cores=4,
            use_batch=False,
        )
        assert result_4.parallel_time_ms == pytest.approx(result_1.serial_time_ms / 4, rel=0.01)

    def test_batch_speedup_applied(self):
        """Batch verification should reduce time for Ed25519."""
        result_no_batch = compute_block_verification_time(
            "Ed25519", txs_per_block=1000, block_time_ms=400.0, num_cores=1,
            use_batch=False,
        )
        result_batch = compute_block_verification_time(
            "Ed25519", txs_per_block=1000, block_time_ms=400.0, num_cores=1,
            use_batch=True,
        )
        assert result_batch.serial_time_ms < result_no_batch.serial_time_ms

    def test_exceeds_block_time_detection(self):
        """SLH-DSA-256s with many txs should exceed Solana's 400ms block time."""
        result = compute_block_verification_time(
            "SLH-DSA-256s", txs_per_block=100, block_time_ms=400.0, num_cores=4,
        )
        # 100 * 8000μs = 800ms serial, 200ms parallel (4 cores)
        # 200ms < 400ms, so should NOT exceed... but with more txs:
        result2 = compute_block_verification_time(
            "SLH-DSA-256s", txs_per_block=1000, block_time_ms=400.0, num_cores=4,
        )
        # 1000 * 8000μs = 8000ms serial, 2000ms parallel
        assert result2.exceeds_block_time is True
        assert result2.verification_bottleneck_ratio > 1.0

    def test_zero_txs(self):
        """Zero transactions should be valid."""
        result = compute_block_verification_time(
            "Ed25519", txs_per_block=0, block_time_ms=400.0, num_cores=4,
        )
        assert result.serial_time_ms == 0.0
        assert result.parallel_time_ms == 0.0
        assert result.exceeds_block_time is False

    def test_negative_txs_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            compute_block_verification_time("Ed25519", txs_per_block=-1, block_time_ms=400.0)

    def test_zero_block_time_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_block_verification_time("Ed25519", txs_per_block=100, block_time_ms=0.0)

    def test_zero_cores_raises(self):
        with pytest.raises(ValueError, match=">= 1"):
            compute_block_verification_time("Ed25519", txs_per_block=100, block_time_ms=400.0, num_cores=0)

    def test_effective_tps_capped_by_verification(self):
        """When verification is the bottleneck, effective TPS should be lower than space TPS."""
        result = compute_block_verification_time(
            "SLH-DSA-256s", txs_per_block=500, block_time_ms=400.0, num_cores=1,
        )
        space_tps = 500 / (400.0 / 1000.0)  # 1250 TPS
        assert result.effective_tps < space_tps

    def test_solana_ed25519_no_bottleneck(self):
        """Ed25519 on Solana should not be verification-bottlenecked."""
        result = compute_block_verification_time(
            "Ed25519", txs_per_block=5000, block_time_ms=400.0, num_cores=8,
        )
        assert result.exceeds_block_time is False

    def test_bottleneck_ratio_meaning(self):
        """Ratio > 1.0 means verification is slower than block production."""
        result = compute_block_verification_time(
            "SLH-DSA-256s", txs_per_block=1000, block_time_ms=400.0, num_cores=1,
        )
        assert result.verification_bottleneck_ratio > 1.0
        assert result.exceeds_block_time is True


# ---------------------------------------------------------------------------
# Verification-limited TPS tests
# ---------------------------------------------------------------------------

class TestComputeVerificationLimitedTps:
    def test_ed25519_high_ceiling(self):
        """Ed25519 should have a very high verification TPS ceiling."""
        tps = compute_verification_limited_tps("Ed25519", block_time_ms=400.0, num_cores=8)
        # 8 cores, 60μs per verify (with batch 0.5 = 30μs), 400ms block
        # = 400000/30 * 8 / 0.4 = very high
        assert tps > 100_000

    def test_slh_dsa_low_ceiling(self):
        """SLH-DSA-256s should have a low verification TPS ceiling."""
        tps = compute_verification_limited_tps("SLH-DSA-256s", block_time_ms=400.0, num_cores=4)
        # 4 cores, 8000μs per verify, 400ms block
        # = 400000/8000 * 4 / 0.4 = 500
        assert tps < 1000

    def test_more_cores_increases_tps(self):
        tps_4 = compute_verification_limited_tps("ML-DSA-65", block_time_ms=12000.0, num_cores=4)
        tps_8 = compute_verification_limited_tps("ML-DSA-65", block_time_ms=12000.0, num_cores=8)
        assert tps_8 > tps_4

    def test_invalid_block_time(self):
        with pytest.raises(ValueError, match="positive"):
            compute_verification_limited_tps("Ed25519", block_time_ms=0.0)

    def test_invalid_cores(self):
        with pytest.raises(ValueError, match=">= 1"):
            compute_verification_limited_tps("Ed25519", block_time_ms=400.0, num_cores=0)

    def test_falcon_vs_mldsa_ceiling(self):
        """Falcon should have higher verification TPS ceiling than ML-DSA."""
        falcon_tps = compute_verification_limited_tps("Falcon-512", block_time_ms=12000.0, num_cores=4)
        mldsa_tps = compute_verification_limited_tps("ML-DSA-65", block_time_ms=12000.0, num_cores=4)
        assert falcon_tps > mldsa_tps
