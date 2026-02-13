"""Reusable Plotly chart builders for the Streamlit app."""

from __future__ import annotations

from typing import List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from blockchain.solana_model import BlockAnalysis
from blockchain.zk_models import ZKProofAnalysis

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

# ZK proof system colors
ZK_COLORS = {
    "Groth16": "#e377c2",    # pink (SNARK)
    "PLONK": "#f7b6d2",      # light pink (SNARK)
    "Halo2": "#c5b0d5",      # light purple (SNARK)
    "STARK-S": "#2ca02c",    # green (quantum-resistant)
    "STARK-L": "#98df8a",    # light green (quantum-resistant)
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


# ---------------------------------------------------------------------------
# ZK proof charts
# ---------------------------------------------------------------------------

def zk_proof_size_vs_gas_chart(analyses: List[ZKProofAnalysis]) -> go.Figure:
    """Scatter plot of proof size vs verification gas cost, colored by quantum resistance."""
    fig = go.Figure()

    for a in analyses:
        color = "#2ca02c" if a.quantum_resistant else "#d62728"
        symbol = "diamond" if a.quantum_resistant else "circle"
        fig.add_trace(go.Scatter(
            x=[a.proof_bytes],
            y=[a.verification_gas],
            mode="markers+text",
            marker=dict(size=16, color=color, symbol=symbol, line=dict(width=1, color="white")),
            text=[a.proof_system],
            textposition="top center",
            name=a.proof_system,
            hovertemplate=(
                f"<b>{a.proof_system}</b><br>"
                f"Proof size: {a.proof_bytes:,} bytes<br>"
                f"Verification gas: {a.verification_gas:,}<br>"
                f"Quantum resistant: {'Yes' if a.quantum_resistant else 'No'}<br>"
                f"<extra></extra>"
            ),
        ))

    fig.update_layout(
        title="ZK Proof Size vs Verification Gas Cost",
        xaxis_title="Proof Size (bytes, log scale)",
        yaxis_title="Verification Gas",
        xaxis_type="log",
        yaxis_type="log",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        title_font_size=16,
        showlegend=False,
    )

    # Add annotations for quantum resistance
    fig.add_annotation(
        text="Green = Quantum Resistant | Red = NOT Quantum Resistant",
        xref="paper", yref="paper", x=0.5, y=-0.15,
        showarrow=False, font=dict(size=11),
    )
    return fig


def zk_throughput_comparison_chart(analyses: List[ZKProofAnalysis]) -> go.Figure:
    """Bar chart comparing ZK proof system throughput on Ethereum."""
    names = [a.proof_system for a in analyses]
    tps_values = [a.throughput_tps for a in analyses]
    colors = ["#2ca02c" if a.quantum_resistant else "#d62728" for a in analyses]

    fig = go.Figure(go.Bar(
        x=names,
        y=tps_values,
        marker_color=colors,
        text=[f"{t:,.1f}" for t in tps_values],
        textposition="outside",
    ))

    fig.update_layout(
        title="Ethereum Throughput by ZK Proof System",
        xaxis_title="Proof System",
        yaxis_title="Transactions per Second",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        title_font_size=16,
    )
    return fig


def zk_vs_signatures_chart(table_rows: List[dict]) -> go.Figure:
    """Grouped bar chart comparing ZK proofs vs signature schemes on Ethereum."""
    df = pd.DataFrame(table_rows)

    color_map = {
        "ZK-STARK": "#2ca02c",
        "ZK-SNARK": "#d62728",
        "Signature": "#1f77b4",
    }

    fig = px.bar(
        df,
        x="Scheme",
        y="TPS",
        color="Type",
        title="Ethereum Throughput: ZK Proofs vs Signature Schemes",
        color_discrete_map=color_map,
        text="TPS",
    )
    fig.update_traces(texttemplate="%{text:,.1f}", textposition="outside")
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickangle=-45,
        font=dict(size=12),
        title_font_size=16,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def qr_radar_chart(chain_scores) -> go.Figure:
    """Radar chart showing QR score dimensions for all chains.

    *chain_scores*: list of ChainQRScore objects.
    """
    chain_colors = {
        "Solana": "#1f77b4",
        "Bitcoin": "#ff7f0e",
        "Ethereum": "#2ca02c",
    }

    fig = go.Figure()
    for cs in chain_scores:
        categories = [d.dimension.replace("_", " ").title() for d in cs.dimensions]
        values = [d.score for d in cs.dimensions]
        # Close the polygon
        categories.append(categories[0])
        values.append(values[0])

        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=categories,
            fill="toself",
            name=f"{cs.chain} ({cs.composite_score:.0f}, {cs.grade})",
            line=dict(color=chain_colors.get(cs.chain, "#7f7f7f")),
            opacity=0.6,
        ))

    fig.update_layout(
        title="Quantum Resistance Score by Dimension",
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        font=dict(size=12),
        title_font_size=16,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    )
    return fig


def qr_composite_bar_chart(chain_scores) -> go.Figure:
    """Horizontal stacked bar chart showing weighted dimension contributions.

    *chain_scores*: list of ChainQRScore objects.
    """
    chain_colors = {
        "Solana": "#1f77b4",
        "Bitcoin": "#ff7f0e",
        "Ethereum": "#2ca02c",
    }
    dim_colors = {
        "throughput_retention": "#636efa",
        "signature_size": "#ef553b",
        "migration_feasibility": "#00cc96",
        "zk_readiness": "#ab63fa",
        "algorithm_diversity": "#ffa15a",
    }

    data = []
    for cs in chain_scores:
        for d in cs.dimensions:
            data.append({
                "Chain": cs.chain,
                "Dimension": d.dimension.replace("_", " ").title(),
                "Weighted Score": d.weighted_score,
                "Raw Score": d.score,
                "Weight": f"{d.weight:.0%}",
            })

    df = pd.DataFrame(data)
    fig = px.bar(
        df,
        y="Chain",
        x="Weighted Score",
        color="Dimension",
        orientation="h",
        title="Composite QR Score Breakdown (Weighted Contributions)",
        text="Weighted Score",
        color_discrete_map={
            "Throughput Retention": dim_colors["throughput_retention"],
            "Signature Size": dim_colors["signature_size"],
            "Migration Feasibility": dim_colors["migration_feasibility"],
            "Zk Readiness": dim_colors["zk_readiness"],
            "Algorithm Diversity": dim_colors["algorithm_diversity"],
        },
    )
    fig.update_traces(texttemplate="%{text:.1f}", textposition="inside")
    fig.update_layout(
        barmode="stack",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        title_font_size=16,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_title="Weighted Score (0-100)",
    )
    return fig


def zk_gas_breakdown_chart(analyses: List[ZKProofAnalysis]) -> go.Figure:
    """Stacked bar showing gas breakdown: base + calldata + verification."""
    data = []
    for a in analyses:
        base_gas = 21_000  # ETH_BASE_TX_GAS
        calldata_gas = a.proof_bytes * 16  # ETH_CALLDATA_GAS_PER_BYTE
        verification_gas = a.verification_gas
        data.append({"System": a.proof_system, "Component": "Base (21k)", "Gas": base_gas})
        data.append({"System": a.proof_system, "Component": "Calldata", "Gas": calldata_gas})
        data.append({"System": a.proof_system, "Component": "Verification", "Gas": verification_gas})

    df = pd.DataFrame(data)
    fig = px.bar(
        df,
        x="System",
        y="Gas",
        color="Component",
        title="Gas Breakdown per ZK Proof Transaction",
        barmode="stack",
        color_discrete_map={
            "Base (21k)": "#636efa",
            "Calldata": "#ff7f0e",
            "Verification": "#ef553b",
        },
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        title_font_size=16,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
