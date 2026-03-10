"""Statistical analysis tools for publication-quality PQC results.

Provides:
- Confidence interval computation (t-distribution based)
- Bootstrap threshold estimation with uncertainty ranges
- Censoring-aware propagation metrics
- Summary statistics generation

These tools transform raw multi-seed sweep data into publication-ready
metrics with proper uncertainty quantification.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def compute_confidence_intervals(
    df: pd.DataFrame,
    metric: str,
    group_col: str = "pqc_fraction",
    confidence: float = 0.95,
) -> pd.DataFrame:
    """Compute mean, std, and CI per group level.

    Uses the t-distribution for small-sample correction.

    Args:
        df: DataFrame with simulation results.
        metric: Column name to compute CIs for.
        group_col: Column to group by (default: pqc_fraction).
        confidence: Confidence level (default 0.95 = 95%).

    Returns:
        DataFrame with columns: group_col, metric_mean, metric_std,
        metric_ci_lower, metric_ci_upper, metric_n.
    """
    from scipy import stats as scipy_stats

    results = []
    for level, group in df.groupby(group_col):
        values = group[metric].dropna().values
        n = len(values)
        if n == 0:
            continue

        if n < 2:
            results.append({
                group_col: level,
                f"{metric}_mean": float(values[0]),
                f"{metric}_std": 0.0,
                f"{metric}_ci_lower": float(values[0]),
                f"{metric}_ci_upper": float(values[0]),
                f"{metric}_n": n,
            })
            continue

        mean = float(np.mean(values))
        std = float(np.std(values, ddof=1))
        se = std / math.sqrt(n)
        t_crit = scipy_stats.t.ppf((1 + confidence) / 2, df=n - 1)
        ci_lower = mean - t_crit * se
        ci_upper = mean + t_crit * se

        results.append({
            group_col: level,
            f"{metric}_mean": round(mean, 6),
            f"{metric}_std": round(std, 6),
            f"{metric}_ci_lower": round(ci_lower, 6),
            f"{metric}_ci_upper": round(ci_upper, 6),
            f"{metric}_n": n,
        })

    return pd.DataFrame(results)


def bootstrap_threshold(
    df: pd.DataFrame,
    pqc_col: str = "pqc_fraction",
    stale_col: str = "stale_rate",
    threshold: float = 0.5,
    n_boot: int = 1000,
    rng_seed: int = 42,
) -> Tuple[float, float, float]:
    """Bootstrap the PQC adoption level where stale_rate crosses a threshold.

    For each bootstrap iteration:
    1. Resample seeds with replacement at each PQC level
    2. Compute mean stale rate per level
    3. Find the crossing point via linear interpolation

    Args:
        df: DataFrame with sweep results.
        pqc_col: Column name for PQC adoption level.
        stale_col: Column name for stale rate.
        threshold: Stale rate threshold to find crossing for.
        n_boot: Number of bootstrap iterations.
        rng_seed: Random seed for reproducibility.

    Returns:
        Tuple of (median_threshold, lower_95, upper_95).
        Returns (NaN, NaN, NaN) if threshold is never crossed.
    """
    rng = np.random.RandomState(rng_seed)
    pqc_levels = sorted(df[pqc_col].unique())

    if len(pqc_levels) < 2:
        return (float("nan"), float("nan"), float("nan"))

    thresholds: List[float] = []
    for _ in range(n_boot):
        means = []
        for level in pqc_levels:
            group = df[df[pqc_col] == level][stale_col].values
            if len(group) == 0:
                means.append(0.0)
                continue
            boot_sample = rng.choice(group, size=len(group), replace=True)
            means.append(float(boot_sample.mean()))

        # Find crossing point via linear interpolation
        crossing = None
        for i in range(len(means) - 1):
            if means[i] < threshold <= means[i + 1]:
                denom = means[i + 1] - means[i]
                if denom > 0:
                    frac = (threshold - means[i]) / denom
                else:
                    frac = 0.5
                crossing = pqc_levels[i] + frac * (pqc_levels[i + 1] - pqc_levels[i])
                break

        if crossing is not None:
            thresholds.append(crossing)
        elif all(m >= threshold for m in means):
            thresholds.append(float(pqc_levels[0]))
        elif all(m < threshold for m in means):
            thresholds.append(float(pqc_levels[-1]))

    if not thresholds:
        return (float("nan"), float("nan"), float("nan"))

    median_t = float(np.median(thresholds))
    lower = float(np.percentile(thresholds, 2.5))
    upper = float(np.percentile(thresholds, 97.5))
    return (round(median_t, 4), round(lower, 4), round(upper, 4))


def censoring_aware_metric(
    propagation_times: List[float],
    slot_budget_ms: float,
) -> float:
    """Fraction of nodes that received the block within the slot budget.

    Unlike p90 (which can be biased by survivors), this gives an
    absolute coverage fraction: "what percentage of the network
    received within the slot budget?"

    This is a censoring-aware metric because nodes that never received
    (or received after the deadline) are counted as failures.

    Args:
        propagation_times: Per-node propagation times in ms.
        slot_budget_ms: Maximum acceptable propagation time.

    Returns:
        Fraction of nodes within budget (0.0 to 1.0).
    """
    if not propagation_times:
        return 0.0
    within = sum(1 for t in propagation_times if t <= slot_budget_ms)
    return within / len(propagation_times)


def generate_summary_statistics(
    df: pd.DataFrame,
    chain: str,
    metrics: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Generate publication-ready summary table with CIs for all key metrics.

    Args:
        df: DataFrame with sweep results for a single chain.
        chain: Chain name (for labeling).
        metrics: List of column names to summarize.

    Returns:
        DataFrame with CIs for each metric at each PQC level.
    """
    if metrics is None:
        metrics = [
            "avg_propagation_p90_ms",
            "stale_rate",
            "effective_tps",
            "avg_verification_time_ms",
        ]

    all_cis = []
    for metric in metrics:
        if metric in df.columns:
            ci_df = compute_confidence_intervals(df, metric)
            ci_df["chain"] = chain
            all_cis.append(ci_df)

    if not all_cis:
        return pd.DataFrame()

    # Merge all CI DataFrames
    result = all_cis[0]
    for ci_df in all_cis[1:]:
        result = result.merge(ci_df, on=["pqc_fraction", "chain"], how="outer")

    return result
