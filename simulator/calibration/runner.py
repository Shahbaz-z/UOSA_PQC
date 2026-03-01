"""Calibration runner for validating simulator accuracy.

Runs multiple simulation trials and compares against real-world
calibration targets to ensure the network model is realistic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from simulator.calibration.targets import (
    CalibrationTarget,
    get_calibration_targets,
)
from simulator.results import SimulationResult

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result of calibration validation."""

    chain: str
    baseline_algorithm: str
    num_runs: int
    metrics: Dict[str, float]
    targets: Dict[str, CalibrationTarget]
    passed: bool
    failures: List[str] = field(default_factory=list)

    def report(self) -> str:
        """Generate human-readable calibration report."""
        lines = [
            f"Calibration Report: {self.chain} ({self.baseline_algorithm})",
            f"Runs: {self.num_runs}",
            "=" * 60,
        ]

        for metric, target in self.targets.items():
            actual = self.metrics.get(metric, 0.0)
            status = "PASS" if target.is_calibrated(actual) else "FAIL"
            lines.append(
                f"  {metric}: {actual:.4f} "
                f"(target: {target.target_value:.4f} +/- {target.tolerance_pct:.0%}) "
                f"[{status}]"
            )
            lines.append(f"    Source: {target.source}")

        lines.append("-" * 60)
        overall = "PASSED" if self.passed else "FAILED"
        lines.append(f"Overall: {overall}")

        if self.failures:
            lines.append(f"Failures: {', '.join(self.failures)}")

        return "\n".join(lines)


def run_calibration(
    chain: str,
    baseline_algorithm: str = None,
    num_runs: int = 3,
    simulation_duration_ms: float = 300_000,
    num_validators: int = 200,
    random_seed: int = 42,
) -> CalibrationResult:
    """Run calibration simulation and validate against targets.

    Runs multiple simulations with different seeds and averages the
    results, then compares against real-world calibration targets.

    Args:
        chain: "solana", "bitcoin", or "ethereum".
        baseline_algorithm: Classical algorithm to use. Defaults to
            chain's baseline (Ed25519 for Solana, ECDSA for others).
        num_runs: Number of simulation runs to average.
        simulation_duration_ms: Duration of each simulation.
        num_validators: Number of validators in the simulated network.
        random_seed: Base seed for reproducibility.

    Returns:
        CalibrationResult with pass/fail status and detailed metrics.
    """
    from simulator.core.engine import DESEngine, SimulationConfig
    from simulator.chains.base import get_chain_config

    chain_config = get_chain_config(chain)
    targets = get_calibration_targets(chain)

    if baseline_algorithm is None:
        baseline_algorithm = chain_config.baseline_algorithm

    logger.info(
        f"Starting calibration: {chain} with {baseline_algorithm}, "
        f"{num_runs} runs, {num_validators} validators"
    )

    # Run multiple simulations
    results: List[SimulationResult] = []

    for i in range(num_runs):
        config = SimulationConfig(
            chain=chain,
            signature_algorithm=baseline_algorithm,
            num_validators=num_validators,
            simulation_duration_ms=simulation_duration_ms,
            random_seed=random_seed + i,
        )

        engine = DESEngine(config)
        result = engine.run()
        results.append(result)

        logger.info(
            f"  Run {i+1}/{num_runs}: "
            f"p90={result.avg_propagation_p90_ms:.1f}ms, "
            f"stale_rate={result.stale_rate:.4f}"
        )

    # Average metrics across runs
    avg_metrics = {
        "propagation_p90_ms": sum(r.avg_propagation_p90_ms for r in results) / len(results),
        "stale_rate": sum(r.stale_rate for r in results) / len(results),
    }

    # Validate against targets
    failures = []
    for metric, target in targets.items():
        actual = avg_metrics.get(metric, 0.0)
        if not target.is_calibrated(actual):
            failures.append(
                f"{metric}: got {actual:.4f}, "
                f"expected {target.target_value:.4f} +/- {target.tolerance_pct:.0%}"
            )

    passed = len(failures) == 0

    result = CalibrationResult(
        chain=chain,
        baseline_algorithm=baseline_algorithm,
        num_runs=num_runs,
        metrics=avg_metrics,
        targets=targets,
        passed=passed,
        failures=failures,
    )

    logger.info(f"Calibration {'PASSED' if passed else 'FAILED'}")
    if failures:
        for f in failures:
            logger.warning(f"  {f}")

    return result
