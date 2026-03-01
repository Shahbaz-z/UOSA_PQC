"""Tests for PoissonArrivalModel."""

import math
import random
import pytest

from simulator.mempool import PoissonArrivalModel


class TestPoissonInit:
    """Constructor and validation tests."""

    def test_valid_construction(self):
        model = PoissonArrivalModel(lambda_tps=500.0, rng=random.Random(42))
        assert model.lambda_tps == 500.0

    def test_zero_lambda_raises(self):
        with pytest.raises(ValueError, match="positive"):
            PoissonArrivalModel(lambda_tps=0.0, rng=random.Random(42))

    def test_negative_lambda_raises(self):
        with pytest.raises(ValueError, match="positive"):
            PoissonArrivalModel(lambda_tps=-1.0, rng=random.Random(42))


class TestInterArrival:
    """Tests for next_inter_arrival_ms sampling."""

    @pytest.fixture
    def model(self):
        return PoissonArrivalModel(lambda_tps=100.0, rng=random.Random(42))

    def test_returns_positive(self, model):
        for _ in range(1000):
            assert model.next_inter_arrival_ms() > 0.0

    def test_mean_matches_expected(self, model):
        """Law of large numbers: sample mean ≈ theoretical mean (1000/λ ms)."""
        n = 50_000
        samples = [model.next_inter_arrival_ms() for _ in range(n)]
        sample_mean = sum(samples) / n
        expected_mean = 1000.0 / model.lambda_tps  # 10 ms
        # Allow ±5% tolerance
        assert abs(sample_mean - expected_mean) / expected_mean < 0.05

    def test_deterministic_with_seed(self):
        m1 = PoissonArrivalModel(lambda_tps=100.0, rng=random.Random(42))
        m2 = PoissonArrivalModel(lambda_tps=100.0, rng=random.Random(42))
        for _ in range(100):
            assert m1.next_inter_arrival_ms() == m2.next_inter_arrival_ms()


class TestExpectedCount:
    """Tests for expected_count_in_interval."""

    def test_expected_count_basic(self):
        model = PoissonArrivalModel(lambda_tps=100.0, rng=random.Random(42))
        # λ=100 tps, 1000 ms = 1 s → expect 100 arrivals
        assert model.expected_count_in_interval(1000.0) == 100.0

    def test_expected_count_fractional(self):
        model = PoissonArrivalModel(lambda_tps=250.0, rng=random.Random(42))
        # λ=250, 400ms = 0.4s → expect 100
        assert model.expected_count_in_interval(400.0) == 100.0

    def test_expected_count_zero_interval(self):
        model = PoissonArrivalModel(lambda_tps=100.0, rng=random.Random(42))
        assert model.expected_count_in_interval(0.0) == 0.0
