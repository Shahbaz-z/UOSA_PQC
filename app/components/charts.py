"""Reusable Plotly chart builders for the Streamlit app."""

from __future__ import annotations

from typing import List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from blockchain.solana_model import BlockAnalysis


def benchmark_bar_chart(df: pd.DataFrame, title: str = "Benchmark Results") -> go.Figure:
    """Grouped bar chart: mean_ms by algorithm, grouped by operation."""
    fig = px.bar(
        df,
        x="algorithm",
        y="mean_ms",
        color="operation",
        barmode="group",
        error_y="stddev_ms",
        title=title,
        labels={"mean_ms": "Time (ms)", "algorithm": "Algorithm"},
    )
    fig.update_layout(legend_title_text="Operation")
    return fig


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
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
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
    fig.update_layout(yaxis_tickformat=".0%")
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
    return fig


def side_by_side_sig_chart(results: dict) -> go.Figure:
    """Side-by-side comparison chart for selected algorithms.

    *results*: dict mapping algorithm name to SignResult-like objects
    with .signature_size and .time_ms attributes.
    """
    data = []
    for algo, sr in results.items():
        data.append({"Algorithm": algo, "Metric": "Signature Size (B)", "Value": sr.signature_size})
        data.append({"Algorithm": algo, "Metric": "Sign Time (ms)", "Value": sr.time_ms})
    df = pd.DataFrame(data)
    fig = px.bar(
        df,
        x="Algorithm",
        y="Value",
        color="Metric",
        barmode="group",
        title="Side-by-Side Algorithm Comparison",
    )
    return fig
