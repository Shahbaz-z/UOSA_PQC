"""Classical baseline calibration for the PQC blockchain simulator.

The simulator must reproduce real-world chain metrics with classical
signatures before its PQC predictions are credible. This module enforces
that requirement by running classical-signature simulations and comparing
them against measured mainnet data.

If calibration fails, PQC scenarios are blocked with a CalibrationError.
This prevents publishing misleading results from an un-validated model.

Calibration targets (2024-2025 mainnet averages):
  Bitcoin:  avg TPS ≈ 4.5, block utilisation ≈ 65%, stale rate ≈ 0.5%
  Ethereum: avg TPS ≈ 14,  block utilisation ≈ 70%, stale rate ≈ 1.5%
  Solana:   avg TPS ≈ 1000 (non-vote), block util ≈ 40%, skip rate ≈ 6.5%

Data sources:
  Bitcoin:  https://mempool.space/graphs/mempool
  Ethereum: https://etherscan.io/charts
  Solana:   https://solanabeach.io  /  https://validators.app
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Calibration targets
# ---------------------------------------------------------------------------

# Each target is (target_value, tolerance_fraction).
# A metric passes if: |simulated - target| / target ≤ tolerance.

CALIBRATION_TARGETS: Dict[str, Dict[str, tuple]] = {
    "bitcoin": {
        # avg_tps: 3-7 TPS range; use 4.5 as central estimate
        # Source: https://mempool.space/graphs/mempool (2024-2025 avg)
        "avg_tps":                 (4.5,     0.20),
        # block_utilisation: fraction of 4M WU used per block
        # Source: https://mempool.space/graphs/block-weight (2024-2025)
        "block_utilisation":       (0.65,    0.25),
        # stale_rate: orphan block rate
        # Source: Bitcoin Wiki, orphan block statistics
        "stale_rate":              (0.005,   0.50),
        # median_fee_sat_vbyte: typical mempool clearing fee (range 10-50)
        # Source: https://mempool.space/graphs/mempool#7d
        "median_fee_sat_vbyte":    (20.0,    0.60),
        # block_prop_p95_ms: 95th percentile propagation time
        # Source: DSN Bitcoin propagation monitoring (2023)
        "block_prop_p95_ms":       (10_000.0, 0.40),
        # min_node_bandwidth_mbps: minimum bandwidth for full node operation
        # Source: Bitcoin Core documentation, hardware requirements
        "min_node_bandwidth_mbps": (10.0,    0.50),
    },
    "ethereum": {
        # avg_tps: 12-15 TPS range for L1 execution layer
        # Source: https://etherscan.io/charts/tx (2024-2025 avg)
        "avg_tps":                 (14.0,    0.20),
        # block_utilisation: fraction of 30M gas used
        # Source: https://etherscan.io/charts/gasused (2024-2025)
        "block_utilisation":       (0.70,    0.25),
        # stale_rate: missed slot rate on Beacon Chain
        # Source: https://beaconcha.in (2024 missed slot stats)
        "stale_rate":              (0.015,   0.50),
        # median_fee_gwei: base fee + priority tip
        # Source: https://etherscan.io/gastracker
        "median_fee_gwei":         (15.0,    0.60),
        # block_prop_p95_ms: 95th percentile block propagation
        # Source: Etherscan block analytics, Ethereum P2P monitoring
        "block_prop_p95_ms":       (3_000.0, 0.40),
        # min_node_bandwidth_mbps: Ethereum node bandwidth requirement
        # Source: Ethereum Foundation hardware recommendations
        "min_node_bandwidth_mbps": (25.0,    0.50),
    },
    "solana": {
        # avg_tps: non-vote transactions; range 700-1500
        # Source: https://solanabeach.io (2024-2025 avg, excluding vote txs)
        "avg_tps":                 (1_000.0, 0.30),
        # block_utilisation: fraction of 6 MB block used
        # Source: Solana Beach block analytics
        "block_utilisation":       (0.40,    0.35),
        # stale_rate: slot skip rate
        # Source: https://validators.app (2024 skip rate stats)
        "stale_rate":              (0.065,   0.50),
        # median_fee_lamports: typical priority fee
        # Source: https://solanabeach.io/stats
        "median_fee_lamports":     (5_000.0, 0.70),
        # block_prop_p95_ms: 95th percentile propagation
        # Source: Solana Beach network metrics
        "block_prop_p95_ms":       (1_500.0, 0.40),
        # min_node_bandwidth_mbps: Solana validator bandwidth requirement
        # Source: Solana documentation (hardware requirements)
        "min_node_bandwidth_mbps": (100.0,   0.50),
    },
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """Result for a single calibration metric.

    Attributes:
        metric:          Metric name.
        target:          Target value from mainnet data.
        simulated:       Value produced by the simulator.
        tolerance:       Acceptable fractional deviation (e.g. 0.20 = 20%).
        relative_error:  |simulated - target| / target.
        passed:          True if relative_error ≤ tolerance.
        source:          Citation for the target value.
    """

    metric: str
    target: float
    simulated: float
    tolerance: float
    relative_error: float
    passed: bool
    source: str = ""

    @classmethod
    def compute(
        cls,
        metric: str,
        target: float,
        simulated: float,
        tolerance: float,
        source: str = "",
    ) -> "MetricResult":
        """Compute a MetricResult from raw values.

        Args:
            metric:    Metric name.
            target:    Target value.
            simulated: Simulated value.
            tolerance: Acceptable fractional deviation.
            source:    Citation string.

        Returns:
            MetricResult with computed relative_error and passed flag.
        """
        # NaN guard: treat NaN simulated values as infinite error.
        # Without this, `nan <= tolerance` evaluates to False in Python, which
        # correctly marks passed=False — but `nan * 100` in generate_report()
        # produces 'nan%' and pollutes overall_error_pct with NaN propagation.
        if math.isnan(simulated):
            rel_err = float("inf")
        elif target == 0:
            rel_err = 0.0 if simulated == 0 else float("inf")
        else:
            rel_err = abs(simulated - target) / abs(target)

        return cls(
            metric         = metric,
            target         = target,
            simulated      = simulated,
            tolerance      = tolerance,
            relative_error = rel_err,
            passed         = rel_err <= tolerance,
            source         = source,
        )


@dataclass
class CalibrationResult:
    """Full calibration result for a chain.

    Attributes:
        chain:    Chain name.
        metrics:  Dict mapping metric name → MetricResult.
        passed:   True if ALL metrics pass their tolerances.
    """

    chain: str
    metrics: Dict[str, MetricResult] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True if every metric passes its tolerance."""
        return all(m.passed for m in self.metrics.values())

    @property
    def failed_metrics(self) -> List[MetricResult]:
        """List of metrics that failed calibration."""
        return [m for m in self.metrics.values() if not m.passed]

    @property
    def overall_error_pct(self) -> float:
        """Mean relative error across all metrics (as percentage).

        Metrics with NaN or inf simulated values (fee/bandwidth metrics not
        available from basic DES runs) are excluded from the mean so they
        do not propagate inf into summary statistics.
        """
        finite_errors = [
            m.relative_error for m in self.metrics.values()
            if math.isfinite(m.relative_error)
        ]
        return 100.0 * (sum(finite_errors) / len(finite_errors)) if finite_errors else 0.0

    def generate_report(self) -> str:
        """Generate a markdown calibration report table.

        Returns:
            Markdown string with per-metric results and pass/fail status.
        """
        lines = [
            f"## Calibration Report: {self.chain.title()}",
            "",
            f"**Overall: {'✅ PASS' if self.passed else '❌ FAIL'}**  ",
            f"Mean relative error: {self.overall_error_pct:.1f}%",
            "",
            "| Metric | Target | Simulated | Error | Tolerance | Status |",
            "|--------|--------|-----------|-------|-----------|--------|",
        ]
        for name, m in self.metrics.items():
            status  = "✅ Pass" if m.passed else "❌ Fail"
            # Display inf (NaN-derived) as 'N/A — not measured by DES'
            if math.isinf(m.relative_error):
                err_str = "N/A"
            else:
                err_str = f"{m.relative_error * 100:.1f}%"
            tol_str = f"{m.tolerance * 100:.1f}%"
            lines.append(
                f"| {name} | {m.target:.3g} | {m.simulated:.3g} "
                f"| {err_str} | tol {tol_str} | {status} |"
            )

        if self.failed_metrics:
            lines += [
                "",
                "### Failed Metrics",
                "",
            ]
            for m in self.failed_metrics:
                lines.append(
                    f"- **{m.metric}**: simulated {m.simulated:.3g} vs "
                    f"target {m.target:.3g} "
                    f"(error {m.relative_error * 100:.1f}%, "
                    f"tolerance {m.tolerance * 100:.1f}%)"
                )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CalibrationError
# ---------------------------------------------------------------------------

class CalibrationError(Exception):
    """Raised when the simulator fails classical baseline calibration.

    Contains the CalibrationResult for diagnostic purposes.
    """

    def __init__(self, result: CalibrationResult) -> None:
        self.result = result
        super().__init__(
            f"Calibration failed for {result.chain}: "
            f"{len(result.failed_metrics)} metric(s) out of tolerance.\n"
            + result.generate_report()
        )


# ---------------------------------------------------------------------------
# CalibrationRunner
# ---------------------------------------------------------------------------

class CalibrationRunner:
    """Runs classical baseline validation against mainnet data.

    Usage:
        runner = CalibrationRunner(chain="bitcoin")
        result = runner.run_classical_baseline()
        if not result.passed:
            raise CalibrationError(result)
    """

    # Sources for citation
    DATA_SOURCES: Dict[str, str] = {
        "bitcoin":  "https://mempool.space/graphs/mempool (2024-2025)",
        "ethereum": "https://etherscan.io/charts (2024-2025)",
        "solana":   "https://solanabeach.io / https://validators.app (2024-2025)",
    }

    def __init__(self, chain: str) -> None:
        """Initialise the runner for a given chain.

        Args:
            chain: Chain name ("bitcoin", "ethereum", "solana").

        Raises:
            ValueError: If the chain has no calibration targets.
        """
        chain = chain.lower()
        if chain not in CALIBRATION_TARGETS:
            raise ValueError(
                f"No calibration targets for chain: {chain!r}. "
                f"Valid: {list(CALIBRATION_TARGETS)}"
            )
        self.chain   = chain
        self.targets = CALIBRATION_TARGETS[chain]
        self.source  = self.DATA_SOURCES.get(chain, "")

    def compute_errors(
        self,
        simulated: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute relative errors for each metric.

        Args:
            simulated: Dict of {metric: simulated_value}.

        Returns:
            Dict of {metric: relative_error_pct}.
        """
        errors: Dict[str, float] = {}
        for metric, (target, _tol) in self.targets.items():
            sim_val = simulated.get(metric)
            if sim_val is None:
                errors[metric] = float("nan")
                continue
            if target == 0:
                errors[metric] = 0.0 if sim_val == 0 else float("inf")
            else:
                errors[metric] = 100.0 * abs(sim_val - target) / abs(target)
        return errors

    def passes_calibration(
        self,
        simulated: Dict[str, float],
        tolerance: float = 0.20,
    ) -> bool:
        """Check whether all simulated metrics are within tolerance.

        NaN safety: a simulated value of float('nan') is treated as a FAIL.
        This prevents the silent-pass bug where `nan > tolerance` evaluates
        to False in Python, causing NaN metrics to erroneously pass.

        Args:
            simulated: Dict of {metric: simulated_value}.
            tolerance: Override global tolerance (default 20%).
                       If None, uses per-metric tolerances from targets.

        Returns:
            True if all metrics pass (no NaN, no None, within tolerance).
        """
        for metric, (target, per_metric_tol) in self.targets.items():
            sim_val = simulated.get(metric)
            if sim_val is None:
                return False
            # NaN guard: Python's nan comparisons always return False, so
            # `nan > tolerance` is False, which would silently pass NaN metrics.
            if math.isnan(sim_val):
                return False
            tol = tolerance if tolerance is not None else per_metric_tol
            if target == 0:
                if sim_val != 0:
                    return False
            else:
                if abs(sim_val - target) / abs(target) > tol:
                    return False
        return True

    def run_classical_baseline(
        self,
        simulated: Optional[Dict[str, float]] = None,
    ) -> CalibrationResult:
        """Run calibration against real-world chain data.

        If `simulated` is provided, validates those values against targets.
        If not provided, attempts to run the simulator engine to generate them.

        Args:
            simulated: Pre-computed simulated metric values.
                       If None, tries to run a quick DES simulation.

        Returns:
            CalibrationResult with per-metric pass/fail details.
        """
        if simulated is None:
            simulated = self._run_simulator_baseline()

        result = CalibrationResult(chain=self.chain)

        for metric, (target, per_metric_tol) in self.targets.items():
            sim_val = simulated.get(metric, float("nan"))
            result.metrics[metric] = MetricResult.compute(
                metric    = metric,
                target    = target,
                simulated = sim_val,
                tolerance = per_metric_tol,
                source    = self.source,
            )

        return result

    def _run_simulator_baseline(self) -> Dict[str, float]:
        """Run a quick DES simulation to produce classical baseline metrics.

        Returns a dict of simulated metric values using the default chain
        parameters and the classical signature algorithm.

        Returns:
            Dict of {metric: simulated_value}.
        """
        from simulator.core.engine import DESEngine, SimulationConfig
        from simulator.chains.base import CHAIN_CONFIGS

        cfg_base = CHAIN_CONFIGS[self.chain]
        sim_cfg = SimulationConfig(
            chain              = self.chain,
            signature_algorithm= cfg_base.baseline_algorithm,
            num_validators     = min(100, cfg_base.target_validators),
            num_full_nodes     = 50,
            simulation_duration_ms = 60_000,  # 1 minute for quick check
            random_seed        = 42,
        )

        engine = DESEngine(sim_cfg)
        result = engine.run()

        # Map SimulationResult fields → calibration metric names
        # The simulator returns propagation times in ms and stale rates as fractions.
        simulated: Dict[str, float] = {}

        # Stale rate — universal
        simulated["stale_rate"] = getattr(result, "stale_rate", float("nan"))

        # Propagation P95
        simulated["block_prop_p95_ms"] = getattr(
            result, "propagation_p95_ms",
            getattr(result, "avg_propagation_p95_ms", float("nan"))
        )

        # Block utilisation — compute from avg block size vs limit
        avg_block_bytes = getattr(result, "avg_block_size_bytes", float("nan"))
        if not math.isnan(avg_block_bytes):
            limit_bytes = cfg_base.block_size_limit
            simulated["block_utilisation"] = avg_block_bytes / limit_bytes
        else:
            simulated["block_utilisation"] = float("nan")

        # TPS — derived from blocks_produced and simulation duration
        blocks_produced = getattr(result, "blocks_produced", 0)
        txs_per_block   = getattr(result, "avg_txs_per_block", 0)
        duration_s      = sim_cfg.simulation_duration_ms / 1_000
        if duration_s > 0 and blocks_produced > 0:
            simulated["avg_tps"] = (blocks_produced * txs_per_block) / duration_s
        else:
            simulated["avg_tps"] = float("nan")

        # Chain-specific fee metric — not available from basic DES, fill with NaN
        # (fee model is in Phase2Engine; basic DES doesn't track fees)
        if self.chain == "bitcoin":
            simulated["median_fee_sat_vbyte"]    = float("nan")
            simulated["min_node_bandwidth_mbps"] = float("nan")
        elif self.chain == "ethereum":
            simulated["median_fee_gwei"]         = float("nan")
            simulated["min_node_bandwidth_mbps"] = float("nan")
        elif self.chain == "solana":
            simulated["median_fee_lamports"]     = float("nan")
            simulated["min_node_bandwidth_mbps"] = float("nan")

        return simulated

    def generate_calibration_report(
        self,
        simulated: Optional[Dict[str, float]] = None,
    ) -> str:
        """Generate a full markdown calibration report.

        Args:
            simulated: Simulated metric values. If None, runs baseline.

        Returns:
            Markdown string.
        """
        result = self.run_classical_baseline(simulated)
        return result.generate_report()

    def validate_or_raise(
        self,
        simulated: Optional[Dict[str, float]] = None,
    ) -> CalibrationResult:
        """Run calibration; raise CalibrationError if it fails.

        Intended to be called at the start of a PQC simulation run.

        Args:
            simulated: Pre-computed simulated values. If None, runs baseline.

        Returns:
            CalibrationResult on success.

        Raises:
            CalibrationError: If any metric fails its tolerance.
        """
        result = self.run_classical_baseline(simulated)
        if not result.passed:
            raise CalibrationError(result)
        return result
