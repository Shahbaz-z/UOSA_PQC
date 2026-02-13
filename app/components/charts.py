"""Reusable Plotly chart builders for the Streamlit app."""

from __future__ import annotations

from typing import List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from blockchain.solana_model import BlockAnalysis


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
    )
    return fig


def throughput_comparison_chart(analyses: List[BlockAnalysis], chain: str = "Solana") -> go.Figure:
    """Bar chart of relative throughput vs baseline."""
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
    )
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
        title=f"{chain}: Transaction Size Breakdown",
        barmode="stack",
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickangle=-45,
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

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            name="Signature Size (bytes)",
            x=algos,
            y=sizes,
            marker_color="steelblue",
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
    )
    fig.update_yaxes(title_text="Signature Size (bytes)", secondary_y=False)
    fig.update_yaxes(title_text="Sign Time (ms)", secondary_y=True)

    return fig
