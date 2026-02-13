"""Chart components wrapping Plotly visualizations."""

from __future__ import annotations

from typing import List, Dict, Any
import reflex as rx
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_reflex.styles.theme import COLORS


def block_space_chart_component(analyses: List[Dict[str, Any]], chain: str = "Solana") -> rx.Component:
    """Horizontal bar chart showing txs_per_block for each signature type."""
    if not analyses:
        return rx.text("No data available", color=COLORS["text_muted"])

    fig = px.bar(
        x=[a["txs_per_block"] for a in analyses],
        y=[a["scheme"] for a in analyses],
        orientation="h",
        color=[a["sig_size"] for a in analyses],
        color_continuous_scale="RdYlGn_r",
        labels={"x": "Txs per Block", "y": "Signature", "color": "Sig Size (B)"},
    )
    fig.update_layout(
        title=f"{chain} Block Capacity by Signature Scheme",
        yaxis={"categoryorder": "total ascending"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["text"]},
        height=400,
    )

    return rx.plotly(data=fig)


def throughput_chart_component(analyses: List[Dict[str, Any]], chain: str = "Solana") -> rx.Component:
    """Bar chart of relative throughput vs baseline."""
    if not analyses:
        return rx.text("No data available", color=COLORS["text_muted"])

    fig = px.bar(
        x=[a["scheme"] for a in analyses],
        y=[a["vs_baseline"] for a in analyses],
        color=[a["tps"] for a in analyses],
        color_continuous_scale="Viridis",
        labels={"x": "Signature", "y": "Relative Throughput (%)", "color": "TPS"},
        text=[f"{a['vs_baseline']:.1f}%" for a in analyses],
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        title=f"{chain}: Throughput Relative to Baseline (100% = parity)",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["text"]},
        xaxis_tickangle=-45,
        height=400,
    )

    return rx.plotly(data=fig)


def signature_size_chart_component(analyses: List[Dict[str, Any]], chain: str = "Solana") -> rx.Component:
    """Stacked bar showing signature vs base overhead per transaction."""
    if not analyses:
        return rx.text("No data available", color=COLORS["text_muted"])

    schemes = [a["scheme"] for a in analyses]
    sig_sizes = [a["sig_size"] for a in analyses]
    base_sizes = [a["tx_size"] - a["sig_size"] for a in analyses]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Base Overhead", x=schemes, y=base_sizes, marker_color=COLORS["secondary"]))
    fig.add_trace(go.Bar(name="Signature", x=schemes, y=sig_sizes, marker_color=COLORS["primary"]))

    fig.update_layout(
        barmode="stack",
        title=f"{chain}: Transaction Size Breakdown",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["text"]},
        xaxis_tickangle=-45,
        yaxis_title="Bytes",
        height=400,
    )

    return rx.plotly(data=fig)


def comparison_chart_component(results: Dict[str, Dict[str, Any]]) -> rx.Component:
    """Dual-axis comparison chart: signature size (bars) and sign time (line)."""
    if not results:
        return rx.text("Run comparison to see chart", color=COLORS["text_muted"])

    algos = list(results.keys())
    sizes = [results[a]["sig_size"] for a in algos]
    times = [results[a]["sign_ms"] for a in algos]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            name="Signature Size (bytes)",
            x=algos,
            y=sizes,
            marker_color=COLORS["primary"],
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
            marker=dict(size=10, color=COLORS["warning"]),
            line=dict(color=COLORS["warning"], width=2),
            text=[f"{t:.3f}" for t in times],
            textposition="top center",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Algorithm Comparison: Signature Size vs Sign Time",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["text"]},
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_tickangle=-45,
        height=450,
    )
    fig.update_yaxes(title_text="Signature Size (bytes)", secondary_y=False)
    fig.update_yaxes(title_text="Sign Time (ms)", secondary_y=True)

    return rx.plotly(data=fig)
