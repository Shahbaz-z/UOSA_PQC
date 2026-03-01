"""Tests for AlgorithmMixGenerator and AlgorithmMixConfig."""

import random
import pytest

from simulator.mempool.algorithm_mix import (
    AlgorithmMixConfig,
    AlgorithmMixGenerator,
    DEFAULT_PQC_WEIGHTS,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


class TestAlgorithmMixConfig:
    """Tests for AlgorithmMixConfig validation and defaults."""

    def test_valid_construction(self):
        cfg = AlgorithmMixConfig(pqc_fraction=0.5)
        assert cfg.pqc_fraction == 0.5
        assert cfg.classical_algo == "Ed25519"
        assert cfg.pqc_weights == DEFAULT_PQC_WEIGHTS

    def test_pqc_fraction_zero(self):
        cfg = AlgorithmMixConfig(pqc_fraction=0.0)
        assert cfg.pqc_fraction == 0.0

    def test_pqc_fraction_one(self):
        cfg = AlgorithmMixConfig(pqc_fraction=1.0)
        assert cfg.pqc_fraction == 1.0

    def test_pqc_fraction_out_of_range_high(self):
        with pytest.raises(ValueError, match="\\[0\\.0, 1\\.0\\]"):
            AlgorithmMixConfig(pqc_fraction=1.1)

    def test_pqc_fraction_out_of_range_negative(self):
        with pytest.raises(ValueError, match="\\[0\\.0, 1\\.0\\]"):
            AlgorithmMixConfig(pqc_fraction=-0.1)

    def test_unknown_classical_algo(self):
        with pytest.raises(ValueError, match="Unknown classical"):
            AlgorithmMixConfig(pqc_fraction=0.5, classical_algo="FakeAlgo")

    def test_unknown_pqc_algo(self):
        with pytest.raises(ValueError, match="Unknown PQC"):
            AlgorithmMixConfig(
                pqc_fraction=0.5,
                pqc_weights={"NonExistent": 1.0},
            )

    def test_custom_pqc_weights(self):
        custom = {"ML-DSA-44": 0.5, "ML-DSA-65": 0.5}
        cfg = AlgorithmMixConfig(pqc_fraction=0.5, pqc_weights=custom)
        assert cfg.pqc_weights == custom


class TestAlgorithmMixGenerator:
    """Tests for the random sampler."""

    @pytest.fixture
    def all_classical(self):
        return AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.0),
            rng=random.Random(42),
        )

    @pytest.fixture
    def all_pqc(self):
        return AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=1.0),
            rng=random.Random(42),
        )

    @pytest.fixture
    def half_pqc(self):
        return AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.5),
            rng=random.Random(42),
        )

    def test_all_classical_returns_ed25519(self, all_classical):
        for _ in range(100):
            assert all_classical.sample() == "Ed25519"

    def test_all_pqc_returns_pqc(self, all_pqc):
        pqc_algos = set(DEFAULT_PQC_WEIGHTS.keys())
        for _ in range(100):
            assert all_pqc.sample() in pqc_algos

    def test_half_pqc_mix(self, half_pqc):
        """With pqc_fraction=0.5, roughly half should be PQC."""
        n = 10_000
        samples = half_pqc.sample_batch(n)
        classical_count = sum(1 for s in samples if s == "Ed25519")
        pqc_count = n - classical_count
        # Allow ±5% tolerance
        assert 0.45 < pqc_count / n < 0.55

    def test_pqc_weight_distribution(self, all_pqc):
        """Verify PQC sub-distribution matches weights."""
        n = 50_000
        samples = all_pqc.sample_batch(n)
        counts = {}
        for s in samples:
            counts[s] = counts.get(s, 0) + 1

        # Check each PQC algo is within ±3% of expected weight
        for algo, weight in DEFAULT_PQC_WEIGHTS.items():
            actual_frac = counts.get(algo, 0) / n
            assert abs(actual_frac - weight) < 0.03, (
                f"{algo}: expected {weight}, got {actual_frac}"
            )

    def test_deterministic_with_seed(self):
        m1 = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.5),
            rng=random.Random(42),
        )
        m2 = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.5),
            rng=random.Random(42),
        )
        for _ in range(100):
            assert m1.sample() == m2.sample()


class TestTxSizeBytes:
    """Tests for tx_size_bytes calculation."""

    def test_ed25519_size(self):
        mix = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=0.0),
            rng=random.Random(42),
        )
        size = mix.tx_size_bytes("Ed25519", base_overhead=250)
        # 250 + 64 (sig) + 32 (pk) = 346
        assert size == 250 + SIGNATURE_SIZES["Ed25519"] + PUBLIC_KEY_SIZES["Ed25519"]

    def test_mldsa65_size(self):
        mix = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=1.0),
            rng=random.Random(42),
        )
        size = mix.tx_size_bytes("ML-DSA-65", base_overhead=250)
        expected = 250 + SIGNATURE_SIZES["ML-DSA-65"] + PUBLIC_KEY_SIZES["ML-DSA-65"]
        assert size == expected

    def test_slh_dsa_size(self):
        mix = AlgorithmMixGenerator(
            config=AlgorithmMixConfig(pqc_fraction=1.0),
            rng=random.Random(42),
        )
        size = mix.tx_size_bytes("SLH-DSA-128f", base_overhead=250)
        expected = 250 + SIGNATURE_SIZES["SLH-DSA-128f"] + PUBLIC_KEY_SIZES["SLH-DSA-128f"]
        assert size == expected
        # SLH-DSA-128f should be much bigger than Ed25519
        ed_size = mix.tx_size_bytes("Ed25519", base_overhead=250)
        assert size > 10 * ed_size  # ~17370 vs ~346
