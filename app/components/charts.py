"""Reusable Plotly chart builders for the Streamlit app."""

from __future__ import annotations

from typing import List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from blockchain.solana_model import BlockAnalysis

# Consistent color scheme for PQC families
FAMILY_COLORS = {
    "Ed25519": "#2ca02c",      # green (classical baseline)
    "ECDSA": "#2ca02c",        # green (classical baseline)
    "Schnorr": "#98df8a",      # light green (classical)
    "Falcon-512": "#1f77b4",   # blue (best PQC)
    "Falcon-1024": "#aec7e8",  # light blue
    "ML-DSA-44": "#ff7f0e",    # orange (NIST standard)
    "ML-DSA-65": "#ffbb78",    # light orange
    "ML-DSA-87": "#d62728",    # red
    "SLH-DSA-128s": "#9467bd", # purple (hash-based)
    "SLH-DSA-128f": "#c5b0d5", # light purple
    "SLH-DSA-192s": "#8c564b", # brown
    "SLH-DSA-192f": "#c49c94", # light brown
    "SLH-DSA-256s": "#e377c2", # pink
    "SLH-DSA-256f": "#f7b6d2", # light pink
}


def _get_color(sig_type: str) -> str:
    """Get consistent color for a signature type."""
    if sig_type.startswith("Hybrid-"):
        return "#17becf"  # cyan for hybrids
    return FAMILY_COLORS.get(sig_type, "#7f7f7f")


def block_space_chart(analyses: List[BlockAnalysis], chain: str = "Solana") -> go.Figure:
    """Horizontal bar chart showing txs_per_block for each signature type."""
    df = pd.DataFrame([
        {
            "Signature": a.signature_type,
            "Txs per Block": a.txs_per_block,
            "Signature Size (B)": a.signature_bytes,
        }
        for a in analyses
    ])
    fig = px.bar(
        df,
        y="Signature",
        x="Txs per Block",
        orientation="h",
        color="Signature Size (B)",
        color_continuous_scale="RdYlGn_r",
        title=f"{chain} Block Capacity by Signature Scheme",
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        title_font_size=16,
    )

    # Add baseline annotation
    baseline = next((a for a in analyses if a.relative_to_baseline == 1.0), None)
    if baseline:
        fig.add_vline(
            x=baseline.txs_per_block,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"Baseline ({baseline.signature_type})",
            annotation_position="top right",
            annotation_font_size=10,
        )
    return fig


def throughput_comparison_chart(analyses: List[BlockAnalysis], chain: str = "Solana") -> go.Figure:
    """Bar chart of relative throughput vs baseline with impact zones."""
    df = pd.DataFrame([
        {
            "Signature": a.signature_type,
            "Relative Throughput": a.relative_to_baseline,
            "TPS": a.throughput_tps,
        }
        for a in analyses
    ])
    fig = px.bar(
        df,
        x="Signature",
        y="Relative Throughput",
        color="TPS",
        color_continuous_scale="Viridis",
        title=f"{chain}: Throughput Relative to Baseline (1.0 = parity)",
        text="Relative Throughput",
    )
    fig.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    fig.update_layout(
        yaxis_tickformat=".0%",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickangle=-45,
        font=dict(size=12),
        title_font_size=16,
    )

    # Add impact zone lines
    fig.add_hline(y=0.9, line_dash="dot", line_color="green", line_width=1,
                  annotation_text="Minimal impact", annotation_position="bottom right",
                  annotation_font_size=9, annotation_font_color="green")
    fig.add_hline(y=0.7, line_dash="dot", line_color="orange", line_width=1,
                  annotation_text="Moderate impact", annotation_position="bottom right",
                  annotation_font_size=9, annotation_font_color="orange")
    fig.add_hline(y=0.4, line_dash="dot", line_color="red", line_width=1,
                  annotation_text="Significant impact", annotation_position="bottom right",
                  annotation_font_size=9, annotation_font_color="red")
    return fig


def signature_size_comparison(analyses: List[BlockAnalysis], chain: str = "Solana") -> go.Figure:
    """Stacked bar showing signature vs base overhead per transaction."""
    data = []
    for a in analyses:
        base = a.tx_size_bytes - a.signature_bytes
        data.append({"Signature Scheme": a.signature_type, "Component": "Base Overhead", "Bytes": base})
        data.append({"Signature Scheme": a.signature_type, "Component": "Signature", "Bytes": a.signature_bytes})
    df = pd.DataFrame(data)
    fig = px.bar(
        df,
        x="Signature Scheme",
        y="Bytes",
        color="Component",
        title=f"{chain}: Transaction Size Breakdown (Signature vs Overhead)",
        barmode="stack",
        color_discrete_map={"Base Overhead": "#636efa", "Signature": "#ef553b"},
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickangle=-45,
        font=dict(size=12),
        title_font_size=16,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def side_by_side_dual_axis_chart(results: dict) -> go.Figure:
    """Dual-axis comparison chart: signature size (left axis) and sign time (right axis).

    Uses separate y-axes so bytes and milliseconds are not conflated on a single scale.

    *results*: dict mapping algorithm name to SignResult-like objects
    with .signature_size and .time_ms attributes.
    """
    algos = list(results.keys())
    sizes = [results[a].signature_size for a in algos]
    times = [results[a].time_ms for a in algos]
    colors = [_get_color(a) for a in algos]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            name="Signature Size (bytes)",
            x=algos,
            y=sizes,
            marker_color=colors,
            opacity=0.8,
            text=[f"{s:,} B" for s in sizes],
            textposition="outside",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            name="Sign Time (ms)",
            x=algos,
            y=times,
            mode="lines+markers+text",
            marker=dict(size=10, color="tomato"),
            line=dict(color="tomato", width=2),
            text=[f"{t:.3f}" for t in times],
            textposition="top center",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Algorithm Comparison: Signature Size vs Sign Time",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_tickangle=-45,
        font=dict(size=12),
        title_font_size=16,
    )
    fig.update_yaxes(title_text="Signature Size (bytes)", secondary_y=False)
    fig.update_yaxes(title_text="Sign Time (ms)", secondary_y=True)

    return fig
