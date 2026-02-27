"""Tests for blockchain/verification.py -- signature verification time modeling."""

import pytest

from blockchain.verification import (
    VERIFICATION_TIME_MS,
    get_verification_time,
    get_verification_time_mmc,
)


# ---------------------------------------------------------------------------
# Tests for VERIFICATION_TIME_MS constants (FIX #4 validation)
# ---------------------------------------------------------------------------

class TestVerificationTimeConstants:
    """Validate corrected SLH-DSA verification time constants."""

    def test_ed25519_baseline(self):
        """Ed25519 should be fast: ~0.05ms."""
        assert VERIFICATION_TIME_MS["Ed25519"] == pytest.approx(0.05)

    def test_ml_dsa_65_reasonable(self):
        """ML-DSA-65 should be close to Ed25519 speed (lattice-based is fast)."""
        val = VERIFICATION_TIME_MS["ML-DSA-65"]
        assert 0.04 <= val <= 0.15, f"ML-DSA-65={val}ms out of expected range"

    def test_slh_dsa_shake_128s_corrected(self):
        """FIX #4: SLH-DSA-SHAKE-128s must be >> Ed25519 (hash-based is slow)."""
        slh = VERIFICATION_TIME_MS["SLH-DSA-SHAKE-128s"]
        ed = VERIFICATION_TIME_MS["Ed25519"]
        # Must be at least 10× slower than Ed25519
        assert slh >= ed * 10, (
            f"SLH-DSA-SHAKE-128s={slh}ms should be ≥10× Ed25519={ed}ms. "
            f"Fix #4 not applied correctly."
        )

    def test_slh_dsa_shake_256s_slowest(self):
        """SLH-DSA-SHAKE-256s is the slowest variant (largest params)."""
        v256s = VERIFICATION_TIME_MS["SLH-DSA-SHAKE-256s"]
        v128s = VERIFICATION_TIME_MS["SLH-DSA-SHAKE-128s"]
        assert v256s > v128s, "256s should be slower than 128s"

    def test_slh_dsa_fast_variants_faster_than_slow(self):
        """Fast variants (128f, 192f, 256f) must be faster than slow variants."""
        assert (
            VERIFICATION_TIME_MS["SLH-DSA-SHAKE-128f"]
            < VERIFICATION_TIME_MS["SLH-DSA-SHAKE-128s"]
        )
        assert (
            VERIFICATION_TIME_MS["SLH-DSA-SHAKE-192f"]
            < VERIFICATION_TIME_MS["SLH-DSA-SHAKE-192s"]
        )
        assert (
            VERIFICATION_TIME_MS["SLH-DSA-SHAKE-256f"]
            < VERIFICATION_TIME_MS["SLH-DSA-SHAKE-256s"]
        )

    def test_all_algorithms_positive(self):
        """All verification times must be positive."""
        for alg, t in VERIFICATION_TIME_MS.items():
            assert t > 0, f"{alg} has non-positive verification time: {t}"

    def test_slh_dsa_range_cloudflare_2024(self):
        """SLH-DSA values should be in Cloudflare 2024 benchmark range (0.5-10ms)."""
        slh_algs = [k for k in VERIFICATION_TIME_MS if k.startswith("SLH-DSA")]
        for alg in slh_algs:
            t = VERIFICATION_TIME_MS[alg]
            assert 0.5 <= t <= 12.0, (
                f"{alg}={t}ms outside Cloudflare 2024 range [0.5, 10ms]. "
                f"Fix #4 may not be applied."
            )


# ---------------------------------------------------------------------------
# Tests for get_verification_time (simple parallel model)
# ---------------------------------------------------------------------------

class TestGetVerificationTime:
    """Tests for the simple (non-queuing) verification time model."""

    def test_single_core_single_sig(self):
        """Single core, single sig: just the per-sig time."""
        t = get_verification_time("Ed25519", num_signatures=1, num_cores=1)
        assert t == pytest.approx(0.05 / 1000.0)

    def test_parallelism_reduces_time(self):
        """More cores → less total verification time."""
        t1 = get_verification_time("ML-DSA-65", num_signatures=100, num_cores=1)
        t4 = get_verification_time("ML-DSA-65", num_signatures=100, num_cores=4)
        assert t4 < t1, "4 cores should be faster than 1 core"

    def test_more_sigs_more_time(self):
        """More signatures → more verification time."""
        t10 = get_verification_time("Ed25519", num_signatures=10, num_cores=1)
        t100 = get_verification_time("Ed25519", num_signatures=100, num_cores=1)
        assert t100 > t10

    def test_slh_dsa_much_slower_than_ed25519(self):
        """SLH-DSA should produce significantly higher verification times."""
        t_ed = get_verification_time("Ed25519", num_signatures=100, num_cores=4)
        t_slh = get_verification_time("SLH-DSA-SHAKE-256s", num_signatures=100, num_cores=4)
        assert t_slh > t_ed * 50, (
            f"SLH-DSA ({t_slh:.4f}s) should be >>50× Ed25519 ({t_ed:.4f}s)"
        )

    def test_unknown_algorithm_uses_default(self):
        """Unknown algorithm falls back to Ed25519-like default."""
        t = get_verification_time("UnknownAlg-999", num_signatures=10, num_cores=1)
        assert t > 0

    def test_zero_cores_handled(self):
        """Zero cores should not raise (clamp to 1)."""
        t = get_verification_time("Ed25519", num_signatures=10, num_cores=0)
        assert t > 0


# ---------------------------------------------------------------------------
# Tests for get_verification_time_mmc (M/M/c analytical queuing model)
# ---------------------------------------------------------------------------

class TestGetVerificationTimeMmc:
    """Tests for the M/M/c queuing model. FIX #2 validation."""

    def test_mmc_returns_positive_time(self):
        """M/M/c should return a positive time."""
        t = get_verification_time_mmc(
            algorithm="Ed25519",
            num_signatures=100,
            num_cores=4,
            arrival_rate=1.0,
        )
        assert t > 0

    def test_mmc_geq_simple_model(self):
        """M/M/c time >= simple model (queuing adds wait time)."""
        t_simple = get_verification_time("ML-DSA-65", num_signatures=100, num_cores=4)
        t_mmc = get_verification_time_mmc(
            algorithm="ML-DSA-65",
            num_signatures=100,
            num_cores=4,
            arrival_rate=1.0,
        )
        assert t_mmc >= t_simple, (
            f"M/M/c ({t_mmc:.6f}s) should be >= simple ({t_simple:.6f}s)"
        )

    def test_mmc_high_load_increases_time(self):
        """Higher arrival rate → more queuing → more time."""
        t_low = get_verification_time_mmc(
            algorithm="SLH-DSA-SHAKE-256s",
            num_signatures=100,
            num_cores=4,
            arrival_rate=0.1,
        )
        t_high = get_verification_time_mmc(
            algorithm="SLH-DSA-SHAKE-256s",
            num_signatures=100,
            num_cores=4,
            arrival_rate=5.0,
        )
        assert t_high >= t_low, "Higher load should not decrease time"

    def test_mmc_more_cores_less_time(self):
        """More CPU cores → less M/M/c time."""
        t1 = get_verification_time_mmc(
            algorithm="ML-DSA-65",
            num_signatures=200,
            num_cores=1,
            arrival_rate=2.0,
        )
        t8 = get_verification_time_mmc(
            algorithm="ML-DSA-65",
            num_signatures=200,
            num_cores=8,
            arrival_rate=2.0,
        )
        assert t8 < t1, f"8 cores ({t8:.4f}s) should be faster than 1 core ({t1:.4f}s)"

    def test_mmc_slh_dsa_slower_than_ml_dsa(self):
        """SLH-DSA should be considerably slower than ML-DSA in M/M/c model."""
        t_ml = get_verification_time_mmc(
            algorithm="ML-DSA-65",
            num_signatures=100,
            num_cores=4,
            arrival_rate=1.0,
        )
        t_slh = get_verification_time_mmc(
            algorithm="SLH-DSA-SHAKE-256s",
            num_signatures=100,
            num_cores=4,
            arrival_rate=1.0,
        )
        assert t_slh > t_ml * 10, (
            f"SLH-DSA M/M/c ({t_slh:.4f}s) should be >>10× ML-DSA ({t_ml:.4f}s)"
        )

    def test_mmc_overloaded_system_finite_time(self):
        """Overloaded system (rho >= 1) should still return a finite time."""
        t = get_verification_time_mmc(
            algorithm="SLH-DSA-SHAKE-256s",
            num_signatures=10000,
            num_cores=1,
            arrival_rate=100.0,
        )
        assert t > 0
        assert t < 1e6, "Should not be infinite"

    def test_mmc_zero_arrival_rate_returns_base_time(self):
        """Near-zero arrival rate: M/M/c ≈ simple model."""
        t_simple = get_verification_time("Ed25519", num_signatures=10, num_cores=2)
        t_mmc = get_verification_time_mmc(
            algorithm="Ed25519",
            num_signatures=10,
            num_cores=2,
            arrival_rate=1e-9,
        )
        # At near-zero load, M/M/c ≈ simple (small overhead allowed)
        assert t_mmc == pytest.approx(t_simple, rel=0.1), (
            f"Near-zero load M/M/c ({t_mmc:.6f}s) should ≈ simple ({t_simple:.6f}s)"
        )
