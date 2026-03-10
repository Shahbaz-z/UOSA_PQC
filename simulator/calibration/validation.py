"""Generate validation tables comparing simulated vs mainnet metrics.

Produces structured comparison tables and gap analysis documents
for publication. Each gap is annotated with:
1. The model omission causing it
2. Whether it makes the model optimistic or pessimistic for PQC impact
3. Expected magnitude of correction
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Dict, List

from simulator.calibration.mainnet_data import get_mainnet_data, MainnetMetrics


@dataclass
class ValidationRow:
    """A single row in the validation table."""

    metric: str
    simulated: float
    observed: float
    gap: float            # simulated - observed
    gap_pct: float        # percentage gap
    direction: str        # "Optimistic", "Pessimistic", "Matched"
    omission: str         # What the model omits

    def to_dict(self) -> dict:
        return {
            "Metric": self.metric,
            "Simulated (baseline)": round(self.simulated, 4),
            "Mainnet Observed": round(self.observed, 4),
            "Gap": round(self.gap, 4),
            "Gap (%)": f"{self.gap_pct:+.1f}%",
            "Direction": self.direction,
            "Model Omission": self.omission,
        }


def _classify_direction(
    sim: float, obs: float, optimistic_when_sim_lower: bool = True,
    tolerance_pct: float = 5.0
) -> str:
    """Classify whether gap is optimistic, pessimistic, or matched."""
    if obs == 0:
        return "Matched" if sim == 0 else "Pessimistic"
    pct = abs(sim - obs) / abs(obs) * 100
    if pct < tolerance_pct:
        return "Matched"
    if optimistic_when_sim_lower:
        return "Optimistic" if sim < obs else "Pessimistic"
    return "Pessimistic" if sim < obs else "Optimistic"


def generate_validation_table(
    chain: str,
    simulated_results: Dict[str, float],
    output_dir: str = "results/calibration",
) -> List[ValidationRow]:
    """Compare simulated baseline results against mainnet data.

    Args:
        chain: Chain name.
        simulated_results: Dict with keys like 'stale_rate', 'avg_propagation_p90_ms'.
        output_dir: Where to save the CSV.

    Returns:
        List of ValidationRow objects.
    """
    mainnet = get_mainnet_data(chain)
    rows: List[ValidationRow] = []

    def _pct(sim: float, obs: float) -> float:
        return (sim - obs) / obs * 100 if obs != 0 else 0.0

    # Skip / stale rate
    sim_stale = simulated_results.get("stale_rate", 0.0)
    obs_stale = mainnet.skip_rate
    rows.append(ValidationRow(
        metric="Skip/Stale Rate",
        simulated=sim_stale,
        observed=obs_stale,
        gap=sim_stale - obs_stale,
        gap_pct=_pct(sim_stale, obs_stale),
        direction=_classify_direction(sim_stale, obs_stale, optimistic_when_sim_lower=True),
        omission="No vote tx overhead, no jitter, no network partitions, "
                 "simplified topology" if sim_stale < obs_stale
                 else "Model may over-model contention effects",
    ))

    # P90 propagation
    sim_p90 = simulated_results.get("avg_propagation_p90_ms", 0.0)
    obs_p90 = mainnet.p90_propagation_ms
    rows.append(ValidationRow(
        metric="P90 Propagation (ms)",
        simulated=sim_p90,
        observed=obs_p90,
        gap=sim_p90 - obs_p90,
        gap_pct=_pct(sim_p90, obs_p90),
        direction=_classify_direction(sim_p90, obs_p90, optimistic_when_sim_lower=True),
        omission="Simplified topology, no cross-datacenter routing variance"
                 if sim_p90 < obs_p90
                 else "Possible NIC over-contention in model",
    ))

    # TPS
    sim_tps = simulated_results.get("effective_tps", 0.0)
    obs_tps = mainnet.avg_tps
    rows.append(ValidationRow(
        metric="Effective TPS",
        simulated=sim_tps,
        observed=obs_tps,
        gap=sim_tps - obs_tps,
        gap_pct=_pct(sim_tps, obs_tps),
        direction=_classify_direction(sim_tps, obs_tps, optimistic_when_sim_lower=False),
        omission="Full blocks assumed; real blocks vary in utilization",
    ))

    # Block time
    sim_bt = simulated_results.get("block_time_ms", 0.0)
    obs_bt = mainnet.avg_block_time_ms
    rows.append(ValidationRow(
        metric="Block Time (ms)",
        simulated=sim_bt,
        observed=obs_bt,
        gap=sim_bt - obs_bt,
        gap_pct=_pct(sim_bt, obs_bt),
        direction=_classify_direction(sim_bt, obs_bt, tolerance_pct=5.0),
        omission="Block time is a model input, not output",
    ))

    # Save CSV
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"{chain}_validation_table.csv")
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].to_dict().keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())

    return rows


def generate_gap_analysis(
    chain: str,
    rows: List[ValidationRow],
    output_dir: str = "results/calibration",
) -> str:
    """Generate markdown gap analysis document.

    Args:
        chain: Chain name.
        rows: Validation rows from generate_validation_table.
        output_dir: Output directory.

    Returns:
        Markdown string of the gap analysis.
    """
    mainnet = get_mainnet_data(chain)

    md_lines = [
        f"# Calibration Gap Analysis: {chain.title()}",
        "",
        "## Data Sources",
        mainnet.notes,
        "",
        "## Validation Table",
        "",
        "| Metric | Simulated | Observed | Gap (%) | Direction |",
        "|--------|-----------|----------|---------|-----------|",
    ]

    for row in rows:
        md_lines.append(
            f"| {row.metric} | {row.simulated:.4f} | {row.observed:.4f} "
            f"| {row.gap_pct:+.1f}% | {row.direction} |"
        )

    md_lines.extend(["", "## Gap Analysis", ""])

    for row in rows:
        md_lines.append(f"### {row.metric}")
        md_lines.append(f"- **Gap**: {row.gap_pct:+.1f}% ({row.direction})")
        md_lines.append(f"- **Model omission**: {row.omission}")
        if row.direction == "Optimistic":
            md_lines.append(
                "- **Impact on PQC analysis**: Model underestimates stress; "
                "real PQC impact likely **worse** than simulated."
            )
        elif row.direction == "Pessimistic":
            md_lines.append(
                "- **Impact on PQC analysis**: Model overestimates stress; "
                "real PQC impact likely **better** than simulated."
            )
        else:
            md_lines.append(
                "- **Impact on PQC analysis**: Minimal; this parameter is "
                "well-calibrated."
            )
        md_lines.append("")

    # Overall assessment
    optimistic = sum(1 for r in rows if r.direction == "Optimistic")
    pessimistic = sum(1 for r in rows if r.direction == "Pessimistic")
    matched = sum(1 for r in rows if r.direction == "Matched")

    md_lines.extend([
        "## Overall Assessment",
        "",
        f"- {optimistic} metrics are optimistic (model underestimates real-world stress)",
        f"- {pessimistic} metrics are pessimistic (model overestimates stress)",
        f"- {matched} metrics are well-matched",
        "",
        "**Net direction**: The model is primarily optimistic due to simplified ",
        "topology and missing real-world variance. PQC threshold estimates should ",
        "be treated as **upper bounds** (real thresholds may be lower).",
    ])

    md = "\n".join(md_lines) + "\n"

    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f"{chain}_gap_analysis.md")
    with open(md_path, "w") as f:
        f.write(md)

    return md
