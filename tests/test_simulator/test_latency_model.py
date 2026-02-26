"""Tests for stochastic latency model."""

import math
import random
import pytest

from simulator.models.latency import LatencyModel, get_latency_model


class TestLatencyModel:
    """Tests for LatencyModel class."""

    def test_lognormal_median(self):
        """Log-normal samples should have median close to base_latency."""
        model = LatencyModel(base_latency_ms=100.0, cv=0.15)
        rng = random.Random(42)

        samples = sorted([model.sample(rng) for _ in range(10000)])
        median = samples[len(samples) // 2]

        # Median should be within 10% of base
        assert 90 < median < 110

    def test_lognormal_all_positive(self):
        """All log-normal samples should be positive."""
        model = LatencyModel(base_latency_ms=50.0, cv=0.30)
        rng = random.Random(42)

        for _ in range(1000):
            assert model.sample(rng) > 0

    def test_lognormal_cv_affects_spread(self):
        """Higher CV should produce more spread in samples."""
        rng1 = random.Random(42)
        rng2 = random.Random(42)

        low_cv = LatencyModel(base_latency_ms=100.0, cv=0.10)
        high_cv = LatencyModel(base_latency_ms=100.0, cv=0.30)

        low_samples = [low_cv.sample(rng1) for _ in range(1000)]
        high_samples = [high_cv.sample(rng2) for _ in range(1000)]

        low_std = (sum((x - 100) ** 2 for x in low_samples) / 1000) ** 0.5
        high_std = (sum((x - 100) ** 2 for x in high_samples) / 1000) ** 0.5

        # Higher CV should have higher standard deviation
        assert high_std > low_std

    def test_zero_cv_returns_base(self):
        """Zero CV should return base latency (no variation)."""
        model = LatencyModel(base_latency_ms=100.0, cv=0.0)
        rng = random.Random(42)

        for _ in range(10):
            assert model.sample(rng) == 100.0

    def test_weibull_distribution(self):
        """Weibull distribution should also produce positive values."""
        model = LatencyModel(
            base_latency_ms=100.0,
            cv=0.15,
            distribution="weibull",
            weibull_k=2.5,
        )
        rng = random.Random(42)

        samples = [model.sample(rng) for _ in range(1000)]
        assert all(s > 0 for s in samples)

    def test_unknown_distribution_returns_base(self):
        """Unknown distribution should return base latency."""
        model = LatencyModel(
            base_latency_ms=100.0,
            cv=0.15,
            distribution="unknown",
        )
        rng = random.Random(42)

        assert model.sample(rng) == 100.0

    def test_percentile_calculation(self):
        """Percentile method should return reasonable values."""
        model = LatencyModel(base_latency_ms=100.0, cv=0.15)

        p50 = model.percentile(50)
        p90 = model.percentile(90)
        p99 = model.percentile(99)

        # 50th percentile should be close to median (base)
        assert 90 < p50 < 110

        # Higher percentiles should be larger
        assert p90 > p50
        assert p99 > p90


class TestGetLatencyModel:
    """Tests for get_latency_model factory function."""

    def test_same_region_low_latency(self):
        """Same region should have low base latency."""
        model = get_latency_model("US-East", "US-East")
        assert model.base_latency_ms == 1.0
        assert model.cv == 0.10

    def test_cross_region_uses_matrix(self):
        """Cross-region should use BASE_LATENCY_MATRIX."""
        model = get_latency_model("US-East", "EU-West")
        assert model.base_latency_ms == 75.0  # Corrected value

    def test_cv_increases_with_distance(self):
        """CV should increase for longer distances."""
        short = get_latency_model("EU-West", "EU-Central")  # ~25ms
        long = get_latency_model("US-East", "Asia-Singapore")  # ~230ms

        assert long.cv > short.cv

    def test_cv_capped(self):
        """CV should be capped at 0.25."""
        model = get_latency_model("US-East", "Asia-Singapore")
        assert model.cv <= 0.25

    def test_symmetric_models(self):
        """Latency models should be symmetric between regions."""
        ab = get_latency_model("US-East", "Asia-Tokyo")
        ba = get_latency_model("Asia-Tokyo", "US-East")

        assert ab.base_latency_ms == ba.base_latency_ms
