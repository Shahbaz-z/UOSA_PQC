"""Simulation results and metrics for analysis and visualization."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class SimulationResult:
    """Results from a network simulation run.

    Designed to be DataFrame-compatible for integration with existing
    chart functions via pd.DataFrame([result.to_dict(), ...]).

    All times are in milliseconds.
    """

    # Configuration
    chain: str
    signature_algorithm: str
    num_validators: int
    num_full_nodes: int
    simulation_duration_ms: float

    # Block metrics
    num_blocks: int
    avg_block_size_bytes: float
    avg_txs_per_block: float

    # Propagation metrics (time for block to reach X% of nodes)
    avg_propagation_p50_ms: float
    avg_propagation_p90_ms: float
    avg_propagation_p95_ms: float
    min_propagation_ms: float = 0.0
    max_propagation_ms: float = 0.0

    # Stale/orphan metrics
    # stale_rate: fraction of blocks where p90 propagation > 90% of block_time_ms.
    # TERMINOLOGY NOTE: this is a PROPAGATION CONGESTION RATE, not the true
    # blockchain orphan/stale rate (which requires a fork-choice model).  A block
    # is flagged here when its 90th-percentile propagation latency suggests the
    # network would be at risk of seeing a competing block win.  Results should
    # be labelled "near-stale rate" or "propagation congestion rate" in papers.
    stale_rate: float = 0.0
    orphan_count: int = 0

    # P90 coverage: fraction of total nodes that received the block before P90
    # was computed.  When coverage < 1.0 (e.g. 0.6), the P90 is computed over
    # only 60% of nodes — potentially flattering the result.  Consumers should
    # check coverage alongside avg_propagation_p90_ms to detect incomplete samples.
    # A coverage of 1.0 means every node received the block within the sim window.
    avg_propagation_p90_coverage: float = 0.0

    # Network metrics
    total_nodes: int = 0
    avg_bandwidth_utilization: float = 0.0
    avg_cpu_utilization: float = 0.0

    # Derived metrics
    effective_tps: float = 0.0
    blocks_per_second: float = 0.0

    def __post_init__(self):
        """Compute derived metrics and validate field sanity."""
        import math
        import warnings

        self.total_nodes = self.num_validators + self.num_full_nodes
        if self.simulation_duration_ms > 0:
            self.blocks_per_second = (
                self.num_blocks / (self.simulation_duration_ms / 1000)
            )
            self.effective_tps = self.blocks_per_second * self.avg_txs_per_block

        # Sanity-check key fields: NaN or negative values indicate engine bugs.
        # Warn rather than raise so downstream analysis can inspect the result.
        _checks = {
            "stale_rate":              self.stale_rate,
            "avg_propagation_p50_ms": self.avg_propagation_p50_ms,
            "avg_propagation_p90_ms": self.avg_propagation_p90_ms,
            "avg_propagation_p95_ms": self.avg_propagation_p95_ms,
            "avg_block_size_bytes":   self.avg_block_size_bytes,
            "effective_tps":          self.effective_tps,
        }
        for name, val in _checks.items():
            if math.isnan(val):
                warnings.warn(
                    f"SimulationResult.{name} is NaN — check engine output.",
                    stacklevel=2,
                )
            elif val < 0:
                warnings.warn(
                    f"SimulationResult.{name} = {val} is negative — check engine output.",
                    stacklevel=2,
                )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for DataFrame construction."""
        return asdict(self)

    @staticmethod
    def to_dataframe(results: List["SimulationResult"]) -> pd.DataFrame:
        """Convert list of results to pandas DataFrame."""
        return pd.DataFrame([r.to_dict() for r in results])


@dataclass
class ComparisonResult:
    """Side-by-side comparison of baseline vs PQC simulation results."""

    chain: str
    baseline_result: SimulationResult
    pqc_results: List[SimulationResult] = field(default_factory=list)

    def propagation_impact(self, algorithm: str) -> Optional[float]:
        """Ratio of PQC propagation time to baseline (>1.0 = slower)."""
        pqc = self._get_pqc_result(algorithm)
        if pqc and self.baseline_result.avg_propagation_p90_ms > 0:
            return pqc.avg_propagation_p90_ms / self.baseline_result.avg_propagation_p90_ms
        return None

    def stale_rate_impact(self, algorithm: str) -> Optional[float]:
        """Ratio of PQC stale rate to baseline (>1.0 = more stales)."""
        pqc = self._get_pqc_result(algorithm)
        if pqc and self.baseline_result.stale_rate > 0:
            return pqc.stale_rate / self.baseline_result.stale_rate
        return None

    def tps_impact(self, algorithm: str) -> Optional[float]:
        """Ratio of PQC TPS to baseline (<1.0 = lower throughput)."""
        pqc = self._get_pqc_result(algorithm)
        if pqc and self.baseline_result.effective_tps > 0:
            return pqc.effective_tps / self.baseline_result.effective_tps
        return None

    def _get_pqc_result(self, algorithm: str) -> Optional[SimulationResult]:
        """Get PQC result by algorithm name."""
        for r in self.pqc_results:
            if r.signature_algorithm == algorithm:
                return r
        return None

    def summary_dataframe(self) -> pd.DataFrame:
        """Generate summary DataFrame with all algorithms."""
        rows = []
        baseline = self.baseline_result

        # Baseline row
        rows.append({
            "algorithm": baseline.signature_algorithm,
            "propagation_p90_ms": baseline.avg_propagation_p90_ms,
            "stale_rate": baseline.stale_rate,
            "effective_tps": baseline.effective_tps,
            "propagation_ratio": 1.0,
            "stale_ratio": 1.0,
            "tps_ratio": 1.0,
            "is_baseline": True,
        })

        # PQC rows
        for pqc in self.pqc_results:
            rows.append({
                "algorithm": pqc.signature_algorithm,
                "propagation_p90_ms": pqc.avg_propagation_p90_ms,
                "stale_rate": pqc.stale_rate,
                "effective_tps": pqc.effective_tps,
                "propagation_ratio": self.propagation_impact(pqc.signature_algorithm),
                "stale_ratio": self.stale_rate_impact(pqc.signature_algorithm),
                "tps_ratio": self.tps_impact(pqc.signature_algorithm),
                "is_baseline": False,
            })

        return pd.DataFrame(rows)
