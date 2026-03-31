"""Tests for simulator/calibration/baseline.py.

Covers CalibrationRunner, MetricResult, CalibrationResult, CalibrationError,
and the generate_report() markdown output.
"""

import math
import pytest
from simulator.calibration.baseline import (
    CalibrationRunner,
    CalibrationResult,
    MetricResult,
    CalibrationError,
    CALIBRATION_TARGETS,
)


class TestMetricResult:
    def test_passes_within_tolerance(self):
        result = MetricResult.compute("tps", 10.0, 10.5, 0.20)
        assert result.passed is True
        assert result.relative_error == pytest.approx(0.05, rel=0.01)

    def test_fails_outside_tolerance(self):
        result = MetricResult.compute("tps", 10.0, 15.0, 0.20)
        # 50% error > 20% tolerance
        assert result.passed is False

    def test_exact_match_passes(self):
        result = MetricResult.compute("stale_rate", 0.005, 0.005, 0.50)
        assert result.passed is True
        assert result.relative_error == 0.0

    def test_zero_target_zero_simulated(self):
        result = MetricResult.compute("x", 0.0, 0.0, 0.20)
        assert result.passed is True
        assert result.relative_error == 0.0

    def test_zero_target_nonzero_simulated(self):
        result = MetricResult.compute("x", 0.0, 5.0, 0.20)
        assert result.passed is False

    def test_tolerance_boundary_edge(self):
        # Exactly at the boundary (20% error, 20% tolerance)
        result = MetricResult.compute("x", 10.0, 12.0, 0.20)
        assert result.passed is True  # 20% ≤ 20%

    def test_metric_name_stored(self):
        result = MetricResult.compute("my_metric", 1.0, 1.0, 0.10)
        assert result.metric == "my_metric"


class TestCalibrationResult:
    def _make_result(self, pass_all: bool) -> CalibrationResult:
        result = CalibrationResult(chain="bitcoin")
        result.metrics["tps"] = MetricResult.compute(
            "tps", 4.5, 4.5 if pass_all else 100.0, 0.20
        )
        result.metrics["stale_rate"] = MetricResult.compute(
            "stale_rate", 0.005, 0.005, 0.50
        )
        return result

    def test_all_passing(self):
        result = self._make_result(pass_all=True)
        assert result.passed is True

    def test_one_failing(self):
        result = self._make_result(pass_all=False)
        assert result.passed is False

    def test_failed_metrics_list(self):
        result = self._make_result(pass_all=False)
        assert len(result.failed_metrics) == 1
        assert result.failed_metrics[0].metric == "tps"

    def test_overall_error_pct_zero_on_perfect(self):
        result = self._make_result(pass_all=True)
        assert result.overall_error_pct == pytest.approx(0.0, abs=0.01)

    def test_report_is_markdown(self):
        result = self._make_result(pass_all=True)
        report = result.generate_report()
        assert "##" in report
        assert "|" in report   # markdown table
        assert "PASS" in report or "FAIL" in report

    def test_report_contains_metric_names(self):
        result = self._make_result(pass_all=False)
        report = result.generate_report()
        assert "tps" in report
        assert "stale_rate" in report


class TestCalibrationRunner:
    def test_invalid_chain_raises(self):
        with pytest.raises(ValueError, match="No calibration targets"):
            CalibrationRunner("polygon")

    def test_valid_chains_construct(self):
        for chain in ["bitcoin", "ethereum", "solana"]:
            runner = CalibrationRunner(chain)
            assert runner.chain == chain

    def test_compute_errors_perfect(self):
        runner = CalibrationRunner("bitcoin")
        # Provide exactly the target values
        perfect = {m: t for m, (t, _) in CALIBRATION_TARGETS["bitcoin"].items()}
        errors = runner.compute_errors(perfect)
        for metric, err in errors.items():
            assert err == pytest.approx(0.0, abs=0.01), f"{metric} error is {err}"

    def test_compute_errors_large_deviation(self):
        runner = CalibrationRunner("bitcoin")
        bad = {m: t * 5 for m, (t, _) in CALIBRATION_TARGETS["bitcoin"].items()}
        errors = runner.compute_errors(bad)
        for err in errors.values():
            if not math.isnan(err):
                assert err > 100  # 400% error

    def test_nan_simulated_value_fails_calibration(self):
        """NaN simulated values must FAIL calibration, not silently pass.

        Bug: Python's `nan > tolerance` evaluates to False, which caused
        passes_calibration() to return True for metrics where the simulated
        value was float('nan') (e.g. fee/bandwidth metrics not available
        from basic DES runs).
        """
        runner = CalibrationRunner("bitcoin")
        # Mix of good value (stale_rate passes) and NaN (should fail)
        mixed = {m: float('nan') for m in CALIBRATION_TARGETS["bitcoin"]}
        mixed["stale_rate"] = CALIBRATION_TARGETS["bitcoin"]["stale_rate"][0]
        # NaN metrics must cause failure
        assert runner.passes_calibration(mixed, tolerance=0.20) is False

    def test_nan_simulated_value_not_silently_passed(self):
        """MetricResult with NaN simulated value should have inf relative_error."""
        result = MetricResult.compute("fee", target=20.0, simulated=float('nan'), tolerance=0.60)
        assert math.isinf(result.relative_error), (
            "NaN simulated value should produce inf relative_error, not nan"
        )
        assert result.passed is False

    def test_overall_error_pct_excludes_inf(self):
        """overall_error_pct should not return NaN when some metrics have inf error."""
        runner = CalibrationRunner("bitcoin")
        # Mix: some metrics good, others NaN (which become inf after fix)
        good_val = {m: t for m, (t, _) in CALIBRATION_TARGETS["bitcoin"].items()}
        good_val["median_fee_sat_vbyte"] = float('nan')  # not available from DES
        result = runner.run_classical_baseline(simulated=good_val)
        # overall_error_pct should be a finite number (excludes the inf metric)
        assert math.isfinite(result.overall_error_pct), (
            f"overall_error_pct should be finite, got {result.overall_error_pct}"
        )

    def test_passes_calibration_with_targets(self):
        runner = CalibrationRunner("ethereum")
        perfect = {m: t for m, (t, _) in CALIBRATION_TARGETS["ethereum"].items()}
        assert runner.passes_calibration(perfect, tolerance=0.0)

    def test_fails_calibration_with_bad_values(self):
        runner = CalibrationRunner("solana")
        bad = {m: t * 100 for m, (t, _) in CALIBRATION_TARGETS["solana"].items()}
        assert runner.passes_calibration(bad, tolerance=0.20) is False

    def test_run_classical_baseline_with_simulated_values(self):
        runner = CalibrationRunner("bitcoin")
        perfect = {m: t for m, (t, _) in CALIBRATION_TARGETS["bitcoin"].items()}
        result = runner.run_classical_baseline(simulated=perfect)
        assert isinstance(result, CalibrationResult)
        assert result.chain == "bitcoin"

    def test_calibration_error_raised_on_failure(self):
        runner = CalibrationRunner("ethereum")
        bad = {m: t * 1000 for m, (t, _) in CALIBRATION_TARGETS["ethereum"].items()}
        with pytest.raises(CalibrationError) as exc_info:
            runner.validate_or_raise(simulated=bad)
        assert "Calibration failed" in str(exc_info.value)
        # The CalibrationError exposes the result
        assert exc_info.value.result.chain == "ethereum"

    def test_validate_or_raise_succeeds_on_perfect(self):
        runner = CalibrationRunner("solana")
        perfect = {m: t for m, (t, _) in CALIBRATION_TARGETS["solana"].items()}
        result = runner.validate_or_raise(simulated=perfect)
        assert result.passed is True

    def test_report_generation(self):
        runner = CalibrationRunner("bitcoin")
        perfect = {m: t for m, (t, _) in CALIBRATION_TARGETS["bitcoin"].items()}
        report = runner.generate_calibration_report(simulated=perfect)
        assert "Bitcoin" in report
        assert "PASS" in report

    def test_all_targets_have_reasonable_tolerances(self):
        for chain, metrics in CALIBRATION_TARGETS.items():
            for metric, (target, tol) in metrics.items():
                assert 0.0 < tol <= 1.0, f"{chain}/{metric} tolerance out of range"
                assert target > 0, f"{chain}/{metric} target is non-positive"
