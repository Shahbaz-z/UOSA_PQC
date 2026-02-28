"""Tab 4: PQC Shock Simulator — Phase 2/3 Monte Carlo results dashboard.

Reads ``results/pqc_sweep.csv`` (210 rows × 30 columns) produced by the
Phase 2/3 parameter sweep and renders three interactive Plotly charts:

1. **The Death Curve** — stale-rate phase transition with seed variance band
2. **The False Bottleneck** — dual-axis block-size vs verification time
3. **Cross-Chain Resilience** — estimated stale rates for Solana / Ethereum / Bitcoin

All heavy data loading is cached via ``st.cache_data`` so Streamlit
re-renders are instantaneous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "results" / "pqc_sweep.csv"

# Chain block-time budgets (ms) — propagation must stay below this
_CHAIN_BLOCK_TIMES: dict[str, float] = {
    "Solana": 400,
    "Ethereum": 12_000,
    "Bitcoin": 600_000,
}

# Colour palette (accessible / consistent with existing charts.py)
_CLR_MAIN = "#1f77b4"         # primary blue
_CLR_BAND = "rgba(31,119,180,0.15)"
_CLR_THRESHOLD = "#d62728"    # red
_CLR_BAR_SIZE = "#ff7f0e"     # orange
_CLR_LINE_VERIF = "#2ca02c"   # green
_CLR_SOLANA = "#9945FF"       # Solana brand purple
_CLR_ETHEREUM = "#627EEA"     # Ethereum brand blue
_CLR_BITCOIN = "#F7931A"      # Bitcoin brand orange


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading sweep results …")
def _load_sweep() -> pd.DataFrame:
    """Load and validate the Monte Carlo sweep CSV."""
    if not _CSV_PATH.exists():
        st.error(
            f"Sweep results not found at `{_CSV_PATH}`.  "
            "Run `python run_experiments.py` first to generate the data."
        )
        st.stop()

    df = pd.read_csv(_CSV_PATH)
    # Ensure pqc_fraction is a proper float percentage for display
    df["pqc_pct"] = (df["pqc_fraction"] * 100).round(1)
    df["avg_block_size_kb"] = df["avg_block_size_bytes"] / 1024
    return df


@st.cache_data(show_spinner="Aggregating across seeds …")
def _aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-PQC-fraction mean ± std across Monte Carlo seeds."""
    agg = (
        df.groupby("pqc_pct")
        .agg(
            stale_mean=("stale_rate", "mean"),
            stale_std=("stale_rate", "std"),
            stale_min=("stale_rate", "min"),
            stale_max=("stale_rate", "max"),
            size_mean=("avg_block_size_kb", "mean"),
            size_std=("avg_block_size_kb", "std"),
            verif_avg_mean=("avg_verification_time_ms", "mean"),
            verif_mean=("max_verification_time_ms", "mean"),
            verif_max=("max_verification_time_ms", "max"),
            prop_p90_mean=("avg_propagation_p90_ms", "mean"),
            prop_p90_std=("avg_propagation_p90_ms", "std"),
            tps_mean=("effective_tps", "mean"),
        )
        .reset_index()
    )
    # Fill NaN std (only 1 seed or all same) with 0
    for col in agg.columns:
        if col.endswith("_std"):
            agg[col] = agg[col].fillna(0)
    return agg


# ---------------------------------------------------------------------------
# Cross-chain stale-rate estimation
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Computing cross-chain estimates …")
def _estimate_cross_chain(df: pd.DataFrame) -> pd.DataFrame:
    """Estimate stale rates for Ethereum & Bitcoin from Solana propagation data.

    Approach: the Solana sweep gives us measured P90 propagation times and
    block sizes at each PQC fraction.  A block goes stale when propagation_P90
    exceeds the chain's block time.  For the *same* block-size profile, longer
    block-time chains have proportionally more headroom.

    We scale the Solana propagation times by (block_size_ratio) for chains
    with different block sizes, then compare against each chain's block time
    to estimate stale probability.  This is a first-order analytical model
    shown alongside the empirical Solana data.
    """
    solana_agg = (
        df.groupby("pqc_pct")
        .agg(
            prop_p90=("avg_propagation_p90_ms", "mean"),
            stale=("stale_rate", "mean"),
        )
        .reset_index()
    )

    rows = []
    for _, r in solana_agg.iterrows():
        pqc = r["pqc_pct"]
        # Solana: use empirical stale rate
        rows.append({"pqc_pct": pqc, "chain": "Solana", "stale_rate": r["stale"]})

        # Ethereum: 12 s blocks — same propagation physics but 30× more time budget.
        # Stale probability ≈ P(propagation > block_time).  With 12 s blocks,
        # the propagation times we see (200-310 ms) are <3% of the budget,
        # so stale rate is effectively 0 until extreme PQC levels.
        eth_stale = max(0, (r["prop_p90"] - _CHAIN_BLOCK_TIMES["Ethereum"]) / _CHAIN_BLOCK_TIMES["Ethereum"])
        rows.append({"pqc_pct": pqc, "chain": "Ethereum", "stale_rate": min(1, eth_stale)})

        # Bitcoin: 600 s blocks — propagation is <0.1% of budget
        btc_stale = max(0, (r["prop_p90"] - _CHAIN_BLOCK_TIMES["Bitcoin"]) / _CHAIN_BLOCK_TIMES["Bitcoin"])
        rows.append({"pqc_pct": pqc, "chain": "Bitcoin", "stale_rate": min(1, btc_stale)})

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------
def _death_curve(agg: pd.DataFrame) -> go.Figure:
    """Chart 1: Stale-rate phase-transition 'Death Curve' with variance band."""
    x = agg["pqc_pct"]
    y = agg["stale_mean"] * 100  # convert to %
    y_upper = (agg["stale_mean"] + agg["stale_std"]).clip(upper=1) * 100
    y_lower = (agg["stale_mean"] - agg["stale_std"]).clip(lower=0) * 100

    fig = go.Figure()

    # Shaded variance band (upper then lower reversed for fill)
    fig.add_trace(go.Scatter(
        x=pd.concat([x, x[::-1]]),
        y=pd.concat([y_upper, y_lower[::-1]]),
        fill="toself",
        fillcolor=_CLR_BAND,
        line=dict(color="rgba(255,255,255,0)"),
        hoverinfo="skip",
        showlegend=True,
        name="± 1σ across 10 seeds",
    ))

    # Main line
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        name="Mean Stale Rate",
        line=dict(color=_CLR_MAIN, width=3),
        marker=dict(size=6),
        hovertemplate="PQC: %{x}%<br>Stale Rate: %{y:.1f}%<extra></extra>",
    ))

    # Min / Max envelope (dotted)
    fig.add_trace(go.Scatter(
        x=x, y=agg["stale_min"] * 100,
        mode="lines",
        name="Min (best seed)",
        line=dict(color=_CLR_MAIN, width=1, dash="dot"),
        hovertemplate="PQC: %{x}%<br>Min Stale: %{y:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=agg["stale_max"] * 100,
        mode="lines",
        name="Max (worst seed)",
        line=dict(color=_CLR_MAIN, width=1, dash="dot"),
        hovertemplate="PQC: %{x}%<br>Max Stale: %{y:.1f}%<extra></extra>",
    ))

    # Vertical threshold at ~85-90% (interpolated 30% stale crossing)
    # Find crossing from the data
    _cross_x = None
    for i in range(len(agg) - 1):
        y1_val = agg.iloc[i]["stale_mean"]
        y2_val = agg.iloc[i + 1]["stale_mean"]
        if y1_val < 0.30 <= y2_val:
            x1_val = agg.iloc[i]["pqc_pct"]
            x2_val = agg.iloc[i + 1]["pqc_pct"]
            _cross_x = x1_val + (0.30 - y1_val) * (x2_val - x1_val) / (y2_val - y1_val)
            break
    if _cross_x is not None:
        fig.add_vline(
            x=_cross_x, line_dash="dash", line_color=_CLR_THRESHOLD, line_width=2,
            annotation_text=f"Critical Threshold (~{_cross_x:.0f}% PQC → 30% Stale)",
            annotation_position="top left",
            annotation_font=dict(size=11, color=_CLR_THRESHOLD),
        )

    # Horizontal 30% stale line (operationally critical)
    fig.add_hline(
        y=30, line_dash="dot", line_color="gray", line_width=1,
        annotation_text="30% Stale Rate",
        annotation_position="bottom right",
        annotation_font=dict(size=10, color="gray"),
    )

    fig.update_layout(
        title=dict(
            text="The Death Curve: Solana Stale Rate vs PQC Adoption",
            font=dict(size=18),
        ),
        xaxis_title="PQC Fraction (%)",
        yaxis_title="Stale Rate (%)",
        yaxis=dict(range=[0, 105]),
        xaxis=dict(dtick=10),
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(size=12),
        hovermode="x unified",
    )
    return fig


def _false_bottleneck(agg: pd.DataFrame) -> go.Figure:
    """Chart 2: Dual-axis block size (bars) vs verification time (line)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Bars: average block size in KB
    fig.add_trace(
        go.Bar(
            x=agg["pqc_pct"],
            y=agg["size_mean"],
            name="Avg Block Size (KB)",
            marker_color=_CLR_BAR_SIZE,
            opacity=0.8,
            hovertemplate="PQC: %{x}%<br>Block Size: %{y:,.0f} KB<extra></extra>",
        ),
        secondary_y=False,
    )

    # Line: average verification time (representative, not inflated max-of-max)
    fig.add_trace(
        go.Scatter(
            x=agg["pqc_pct"],
            y=agg["verif_avg_mean"],
            name="Avg Verification (ms)",
            mode="lines+markers",
            line=dict(color=_CLR_LINE_VERIF, width=3),
            marker=dict(size=7, symbol="diamond"),
            hovertemplate="PQC: %{x}%<br>Verification: %{y:.1f} ms<extra></extra>",
        ),
        secondary_y=True,
    )

    # Faint line: worst-case (max of max) for context
    fig.add_trace(
        go.Scatter(
            x=agg["pqc_pct"],
            y=agg["verif_max"],
            name="Worst-Case Single Block (ms)",
            mode="lines",
            line=dict(color=_CLR_LINE_VERIF, width=1, dash="dot"),
            hovertemplate="PQC: %{x}%<br>Worst-case: %{y:.1f} ms<extra></extra>",
        ),
        secondary_y=True,
    )

    # Horizontal line: Solana 400 ms slot limit
    fig.add_hline(
        y=400, line_dash="dash", line_color=_CLR_THRESHOLD, line_width=2,
        annotation_text="Solana 400 ms Slot Limit",
        annotation_position="top right",
        annotation_font=dict(size=11, color=_CLR_THRESHOLD),
        secondary_y=True,
    )

    fig.update_layout(
        title=dict(
            text="The False Bottleneck: Block Size Bloat vs Verification Time",
            font=dict(size=18),
        ),
        xaxis_title="PQC Fraction (%)",
        xaxis=dict(dtick=10),
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(size=12),
        hovermode="x unified",
        bargap=0.3,
    )
    fig.update_yaxes(title_text="Avg Block Size (KB)", secondary_y=False)
    fig.update_yaxes(
        title_text="Verification Time (ms)",
        secondary_y=True,
        range=[0, 450],  # keep the 400 ms slot line visible; worst-case ~196 ms
    )
    return fig


def _cross_chain_resilience(cc: pd.DataFrame) -> go.Figure:
    """Chart 3: Grouped bar chart comparing stale rates at multiple PQC levels."""
    # Show comparison at 0%, 20%, 30%, 50%, 70%, 100% PQC
    key_levels = [0, 20, 30, 50, 70, 100]
    cc_filtered = cc[cc["pqc_pct"].isin(key_levels)].copy()
    cc_filtered["stale_pct"] = cc_filtered["stale_rate"] * 100

    chain_colors = {
        "Solana": _CLR_SOLANA,
        "Ethereum": _CLR_ETHEREUM,
        "Bitcoin": _CLR_BITCOIN,
    }

    fig = go.Figure()
    for chain in ["Solana", "Ethereum", "Bitcoin"]:
        subset = cc_filtered[cc_filtered["chain"] == chain]
        fig.add_trace(go.Bar(
            x=[f"{int(p)}%" for p in subset["pqc_pct"]],
            y=subset["stale_pct"],
            name=chain,
            marker_color=chain_colors[chain],
            hovertemplate=f"{chain}<br>PQC: %{{x}}<br>Stale: %{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(
        title=dict(
            text="Cross-Chain Resilience: Stale Rate by PQC Adoption Level",
            font=dict(size=18),
        ),
        xaxis_title="PQC Adoption Level",
        yaxis_title="Stale Rate (%)",
        yaxis=dict(range=[0, 105]),
        barmode="group",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(size=12),
    )
    return fig


# ---------------------------------------------------------------------------
# Propagation P90 chart (bonus)
# ---------------------------------------------------------------------------
def _propagation_chart(agg: pd.DataFrame) -> go.Figure:
    """Bonus chart: P90 propagation latency with error band."""
    x = agg["pqc_pct"]
    y = agg["prop_p90_mean"]
    y_upper = agg["prop_p90_mean"] + agg["prop_p90_std"]
    y_lower = (agg["prop_p90_mean"] - agg["prop_p90_std"]).clip(lower=0)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=pd.concat([x, x[::-1]]),
        y=pd.concat([y_upper, y_lower[::-1]]),
        fill="toself",
        fillcolor="rgba(148,69,255,0.15)",
        line=dict(color="rgba(255,255,255,0)"),
        hoverinfo="skip",
        showlegend=True,
        name="± 1σ",
    ))

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        name="Mean P90 Propagation",
        line=dict(color=_CLR_SOLANA, width=3),
        marker=dict(size=6),
        hovertemplate="PQC: %{x}%<br>P90: %{y:.1f} ms<extra></extra>",
    ))

    fig.add_hline(
        y=400, line_dash="dash", line_color=_CLR_THRESHOLD, line_width=2,
        annotation_text="Solana 400 ms Slot Limit",
        annotation_position="bottom right",
        annotation_font=dict(size=11, color=_CLR_THRESHOLD),
    )

    fig.update_layout(
        title=dict(text="P90 Propagation Latency vs PQC Adoption", font=dict(size=18)),
        xaxis_title="PQC Fraction (%)",
        yaxis_title="Propagation P90 (ms)",
        xaxis=dict(dtick=10),
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(size=12),
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------
def render(tab) -> None:
    """Render the PQC Shock Simulator tab inside the given Streamlit tab."""
    with tab:
        st.header("PQC Shock Simulator")
        st.caption(
            "Phase 2/3 Monte Carlo results: 21 PQC levels × 10 random seeds = 210 "
            "discrete-event simulations with Poisson arrivals, bounded mempool, and "
            "heterogeneous signature verification."
        )

        # ---- Load data ----
        df = _load_sweep()
        agg = _aggregate(df)
        cc = _estimate_cross_chain(df)

        # ---- KPI metric cards (dynamic from DataFrame) ----
        st.divider()

        # Compute dynamic KPI values from the actual sweep data
        baseline = agg.loc[agg["pqc_pct"] == 0.0].iloc[0]
        row_20 = agg.loc[agg["pqc_pct"] == 20.0].iloc[0] if 20.0 in agg["pqc_pct"].values else None
        row_100 = agg.loc[agg["pqc_pct"] == 100.0].iloc[0]
        block_time_ms = 400.0  # Solana slot time

        # ------------------------------------------------------------------
        # Critical Threshold: find PQC level where stale rate first exceeds
        # 30%.  At 30% stale, nearly one-in-three blocks are orphaned — a
        # level widely considered operationally critical for any chain.
        # We use linear interpolation between the two bracketing data points
        # for a precise crossing estimate.
        # ------------------------------------------------------------------
        _STALE_CRIT = 0.30  # 30 % stale-rate threshold
        crit_value = "None found"
        crit_delta = ""
        # Walk sorted PQC levels and interpolate the crossing
        for i in range(len(agg) - 1):
            y1 = agg.iloc[i]["stale_mean"]
            y2 = agg.iloc[i + 1]["stale_mean"]
            if y1 < _STALE_CRIT <= y2:
                x1 = agg.iloc[i]["pqc_pct"]
                x2 = agg.iloc[i + 1]["pqc_pct"]
                crossing = x1 + (_STALE_CRIT - y1) * (x2 - x1) / (y2 - y1)
                crit_value = f"~{crossing:.0f}% PQC"
                crit_delta = f"Stale rate exceeds {_STALE_CRIT*100:.0f}% threshold"
                break
        if crit_value == "None found":
            # Fallback: maybe the first data point already exceeds threshold
            first_above = agg[agg["stale_mean"] >= _STALE_CRIT]
            if not first_above.empty:
                crit_value = f"{first_above.iloc[0]['pqc_pct']:.0f}% PQC"
                crit_delta = f"{first_above.iloc[0]['stale_mean']*100:.0f}%+ stale rate"
            else:
                max_stale_row = agg.loc[agg["stale_mean"].idxmax()]
                crit_delta = f"Max {max_stale_row['stale_mean']*100:.0f}% at {max_stale_row['pqc_pct']:.0f}% PQC"

        # ------------------------------------------------------------------
        # Block size at 20% PQC vs baseline
        # ------------------------------------------------------------------
        if row_20 is not None:
            size_20_kb = row_20["size_mean"]
            size_0_kb = baseline["size_mean"]
            size_ratio = size_20_kb / size_0_kb if size_0_kb > 0 else 0
            size_value = f"{size_20_kb:.0f} KB"
            size_delta = f"{size_ratio:.0f}× baseline ({size_0_kb:.0f} KB)"
        else:
            size_value = "N/A"
            size_delta = "No 20% data"

        # ------------------------------------------------------------------
        # Verification Time at 100% PQC
        # Use the *average* verification time (avg_verification_time_ms)
        # across all blocks and seeds — this is the representative metric.
        # The previous code used max-of-max (196 ms), which is the single
        # worst block from the single worst seed — a double-maximum that
        # over-states typical verification load.
        # ------------------------------------------------------------------
        # Compute mean of avg_verification_time_ms at 100% PQC from raw data
        verify_100_avg = df.loc[
            df["pqc_fraction"] == 1.0, "avg_verification_time_ms"
        ].mean()
        verify_100_worst = row_100["verif_max"]  # max-of-max, kept for context
        verify_ratio = block_time_ms / verify_100_avg if verify_100_avg > 0 else float("inf")
        verify_value = f"{verify_100_avg:.1f} ms"
        verify_delta = f"{verify_ratio:.0f}× below {block_time_ms:.0f} ms slot (worst: {verify_100_worst:.0f} ms)"

        # ------------------------------------------------------------------
        # Root Cause: compare what fraction of the slot budget each factor
        # actually consumes.  Propagation (driven by block-size bloat) eats
        # 85 % of the 400 ms slot at 100 % PQC, while even the worst-case
        # single-block verification (196 ms) is only 49 %.  The average
        # verification (~32 ms) is just 8 % of the slot.  Block-size bloat
        # causing propagation delay is unambiguously the bottleneck.
        # ------------------------------------------------------------------
        prop_pct_of_slot = row_100["prop_p90_mean"] / block_time_ms
        verify_pct_of_slot = verify_100_avg / block_time_ms
        size_bloat = row_100["size_mean"] / baseline["size_mean"] if baseline["size_mean"] > 0 else 0

        if prop_pct_of_slot > verify_pct_of_slot:
            root_value = "Bandwidth (Data Bloat)"
            root_delta = f"{size_bloat:.0f}× block inflation → NOT Compute"
        else:
            root_value = "Compute"
            root_delta = "NOT Bandwidth"

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric(
                label="Critical Threshold",
                value=crit_value,
                delta=crit_delta,
                delta_color="inverse",
                help="The PQC adoption level at which Solana's mean stale-block "
                     f"rate exceeds {_STALE_CRIT*100:.0f}%, signalling severe "
                     "network degradation (nearly 1-in-3 blocks orphaned).",
            )
        with m2:
            st.metric(
                label="Block Size at 20%",
                value=size_value,
                delta=size_delta,
                delta_color="inverse",
                help="Average block size at 20% PQC adoption vs 0% baseline.",
            )
        with m3:
            st.metric(
                label="Avg Verification at 100%",
                value=verify_value,
                delta=verify_delta,
                delta_color="normal",
                help="Mean block-verification time at 100% PQC (averaged across "
                     "all 25 blocks × 10 seeds). Even the worst single block "
                     f"({verify_100_worst:.0f} ms) remains well below Solana's "
                     f"{block_time_ms:.0f} ms slot budget.",
            )
        with m4:
            st.metric(
                label="Root Cause",
                value=root_value,
                delta=root_delta,
                delta_color="off",
                help="Whether block-space bloat (bandwidth) or signature "
                     "verification (compute) is the primary bottleneck.",
            )

        st.divider()

        # ---- Chart 1: The Death Curve ----
        st.subheader("1. The Death Curve — Phase Transition")
        st.plotly_chart(_death_curve(agg), use_container_width=True)

        with st.expander("Methodology: Stale Rate Calculation"):
            st.markdown(
                "A block is **stale** when its P90 propagation latency exceeds 90% of "
                "the chain's block time (0.9 × 400 ms = 360 ms for Solana). The stale rate "
                "is the fraction of blocks that go stale across 25 simulated blocks per run.\n\n"
                "**Variance band:** The shaded region shows ± 1 standard deviation "
                "across 10 independent random seeds at each PQC level. The dotted "
                "lines show the absolute min / max across seeds.\n\n"
                "**Key observation:** With corrected verification benchmarks (Cloudflare "
                "2024) and realistic block fill, the stale rate rises **gradually** "
                "from 0% at the baseline to ~34% at 100% PQC. The phase transition "
                "occurs around **~85–90% PQC adoption**, where the mean stale rate "
                "crosses 30% (one-in-three blocks orphaned). The primary driver is "
                "block-size bloat (21× larger blocks) causing propagation delays that "
                "exceed Solana's 400 ms slot budget."
            )

        st.divider()

        # ---- Chart 2: The False Bottleneck ----
        st.subheader("2. The False Bottleneck — Size vs Compute")
        st.plotly_chart(_false_bottleneck(agg), use_container_width=True)

        with st.expander("Methodology: Dual-Axis Interpretation"):
            st.markdown(
                "**Left axis (orange bars):** Average block size in KB. PQC signatures "
                "(ML-DSA-44: 2,420 B, ML-DSA-65: 3,293 B, SLH-DSA-128f: 17,088 B) "
                "are 38–267× larger than Ed25519 (64 B), causing block-size inflation.\n\n"
                "**Right axis (green line):** Average block verification time across "
                "all Monte Carlo seeds. At 100% PQC, the mean verification time is "
                "~32 ms — just **8% of the 400 ms slot limit**. Even the worst single "
                "block from the worst seed (dotted line, ~196 ms) stays below the "
                "slot budget.\n\n"
                "**Implication:** Verification time is a _false bottleneck_. The real "
                "threat is block-size bloat (21× inflation) driving propagation delays. "
                "Hardware acceleration for signature verification would **not** solve "
                "the problem. Signature compression, aggregation, or application-layer "
                "batching are required to address the real bottleneck."
            )

        st.divider()

        # ---- Chart 3: Cross-Chain Resilience ----
        st.subheader("3. Cross-Chain Resilience")
        st.plotly_chart(_cross_chain_resilience(cc), use_container_width=True)

        with st.expander("Methodology: Cross-Chain Estimation"):
            st.markdown(
                "Bitcoin (10-minute blocks) and Ethereum (12-second blocks) are estimated "
                "using the same propagation-latency profile measured in the Solana sweep.\n\n"
                "Since measured P90 propagation times peak at ~341 ms (at 100% PQC), "
                "which is **far below** Ethereum's 12,000 ms and Bitcoin's 600,000 ms "
                "block times, both chains show **zero stale blocks** at all PQC levels.\n\n"
                "**Key insight:** Slow block times provide enormous propagation headroom. "
                "Solana's 400 ms slots make it uniquely vulnerable to PQC signature bloat, "
                "while Bitcoin and Ethereum can absorb the transition with negligible impact "
                "on block propagation."
            )

        st.divider()

        # ---- Bonus: Propagation P90 ----
        st.subheader("4. Propagation Latency Scaling")
        st.plotly_chart(_propagation_chart(agg), use_container_width=True)

        with st.expander("Methodology: Propagation Model"):
            st.markdown(
                "Propagation latency is modelled as a function of block size and "
                "inter-node RTT (calibrated from AWS CloudPing February 2026 data). "
                "The P90 value represents the 90th-percentile propagation time across "
                "all validator-to-validator paths.\n\n"
                "At 100% PQC, P90 increases 1.6× (215 ms → 341 ms), reaching **85% "
                "of the 400 ms slot budget**. Combined with the 21× block-size inflation, "
                "this propagation pressure is the primary driver of the stale-rate "
                "phase transition observed at ~85–90% PQC adoption."
            )

        # ---- Raw data explorer ----
        st.divider()
        st.subheader("Raw Data Explorer")
        with st.expander("View / download the full 210-row sweep dataset"):
            st.dataframe(df, use_container_width=True, height=400)
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download pqc_sweep.csv",
                csv_bytes,
                "pqc_sweep.csv",
                "text/csv",
            )
