"""Tests for statistical analysis tools."""

import math
import pytest
import numpy as np
import pandas as pd

from analysis.statistical_analysis import (
    compute_confidence_intervals,
    bootstrap_threshold,
    censoring_aware_metric,
    generate_summary_statistics,
)


class TestConfidenceIntervals:
    """Test CI computation."""

    def test_basic_ci(self):
        """Known data: 10 values with mean=100, should get CI around 100."""
        data = {
            "pqc_fraction": [0.0] * 10,
            "stale_rate": [100 + i for i in range(10)],
        }
        df = pd.DataFrame(data)
        result = compute_confidence_intervals(df, "stale_rate")
        assert len(result) == 1
        row = result.iloc[0]
        assert 95 < row["stale_rate_mean"] < 115
        assert row["stale_rate_ci_lower"] < row["stale_rate_mean"]
        assert row["stale_rate_ci_upper"] > row["stale_rate_mean"]

    def test_multiple_groups(self):
        """Should compute CIs per group."""
        data = {
            "pqc_fraction": [0.0] * 5 + [0.5] * 5 + [1.0] * 5,
            "stale_rate": [0.0] * 5 + [0.3] * 5 + [0.9] * 5,
        }
        df = pd.DataFrame(data)
        result = compute_confidence_intervals(df, "stale_rate")
        assert len(result) == 3  # Three PQC levels

    def test_single_value(self):
        """Single value: CI = point estimate."""
        data = {"pqc_fraction": [0.5], "stale_rate": [0.5]}
        df = pd.DataFrame(data)
        result = compute_confidence_intervals(df, "stale_rate")
        row = result.iloc[0]
        assert row["stale_rate_mean"] == 0.5
        assert row["stale_rate_ci_lower"] == 0.5
        assert row["stale_rate_ci_upper"] == 0.5

    def test_zero_variance(self):
        """All same values: CI has zero width."""
        data = {"pqc_fraction": [0.0] * 5, "stale_rate": [0.1] * 5}
        df = pd.DataFrame(data)
        result = compute_confidence_intervals(df, "stale_rate")
        row = result.iloc[0]
        assert row["stale_rate_ci_lower"] == pytest.approx(0.1, abs=0.001)
        assert row["stale_rate_ci_upper"] == pytest.approx(0.1, abs=0.001)


class TestBootstrapThreshold:
    """Test bootstrap threshold estimation."""

    def test_known_crossing(self):
        """Data with clear crossing at 50% PQC."""
        np.random.seed(42)
        rows = []
        for pqc in [0.0, 0.25, 0.50, 0.75, 1.0]:
            for seed in range(20):
                stale = pqc * 0.8 + np.random.normal(0, 0.05)
                stale = max(0, min(1, stale))
                rows.append({"pqc_fraction": pqc, "stale_rate": stale})
        df = pd.DataFrame(rows)

        median_t, lower, upper = bootstrap_threshold(
            df, threshold=0.3, n_boot=500
        )
        # Should cross around 0.375 (0.3 / 0.8)
        assert 0.2 < median_t < 0.6
        assert lower <= median_t <= upper

    def test_never_crosses(self):
        """Data that never crosses threshold."""
        rows = []
        for pqc in [0.0, 0.5, 1.0]:
            for seed in range(10):
                rows.append({"pqc_fraction": pqc, "stale_rate": 0.01})
        df = pd.DataFrame(rows)

        median_t, lower, upper = bootstrap_threshold(
            df, threshold=0.5, n_boot=100
        )
        # Should return last PQC level
        assert median_t == 1.0

    def test_single_level(self):
        """Single PQC level: should return NaN."""
        data = {"pqc_fraction": [0.5] * 5, "stale_rate": [0.3] * 5}
        df = pd.DataFrame(data)
        median_t, _, _ = bootstrap_threshold(df, threshold=0.5)
        assert math.isnan(median_t)


class TestCensoringAwareMetric:
    """Test censoring-aware propagation metric."""

    def test_all_within_budget(self):
        """All nodes within budget → 1.0."""
        times = [100, 200, 300, 350, 399]
        assert censoring_aware_metric(times, 400) == 1.0

    def test_none_within_budget(self):
        """All nodes exceed budget → 0.0."""
        times = [500, 600, 700]
        assert censoring_aware_metric(times, 400) == 0.0

    def test_partial(self):
        """Half within budget → 0.5."""
        times = [100, 200, 500, 600]
        assert censoring_aware_metric(times, 400) == 0.5

    def test_empty(self):
        """Empty list → 0.0."""
        assert censoring_aware_metric([], 400) == 0.0

    def test_boundary(self):
        """Exact boundary: equal to budget counts as within."""
        assert censoring_aware_metric([400], 400) == 1.0


class TestSummaryStatistics:
    """Test summary statistics generation."""

    def test_basic_summary(self):
        """Should produce summary with CIs for each metric."""
        data = {
            "pqc_fraction": [0.0] * 5 + [1.0] * 5,
            "avg_propagation_p90_ms": [100] * 5 + [500] * 5,
            "stale_rate": [0.0] * 5 + [0.5] * 5,
            "effective_tps": [1000] * 5 + [500] * 5,
        }
        df = pd.DataFrame(data)
        result = generate_summary_statistics(df, "solana")
        assert len(result) > 0
        assert "chain" in result.columns

    def test_missing_metric(self):
        """Should skip metrics not in DataFrame."""
        data = {"pqc_fraction": [0.0] * 5, "stale_rate": [0.1] * 5}
        df = pd.DataFrame(data)
        result = generate_summary_statistics(df, "solana")
        assert len(result) > 0
