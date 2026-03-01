"""Tab 1: Overview \u2014 landing page with onboarding, vulnerability context, and
cross-chain throughput comparison.

Merges the old Cross-Chain Summary tab (Tab 3) with a new introductory section
so first-time users get context before diving into per-chain analysis.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from blockchain.chain_models import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SOLANA_VOTE_TX_PCT_REALISTIC,
    SOLANA_BLOCK_SIZE_BYTES,
    SOLANA_BASE_TX_OVERHEAD,
    SOLANA_SLOT_TIME_MS,
)
from app.utils import format_bytes, throughput_impact_category, threat_badge, CHAIN_COLORS


# ---------------------------------------------------------------------------
# Cached computation (eliminates redundant recomputation on re-renders)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Computing cross-chain analyses \u2026")
def _get_default_analyses():
    """Run all three chain analyses with default parameters (cached)."""
    return (
        compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC),
        compare_all_bitcoin(),
        compare_all_ethereum(),
    )


# ---------------------------------------------------------------------------
# Heatmap chart (replaces the plain table from old Tab 3)
# ---------------------------------------------------------------------------
def _retention_heatmap(sol_comp, btc_comp, eth_comp) -> go.Figure:
    """Create a throughput-retention heatmap: algorithms \u00d7 chains."""
    highlight_algos = ["Falcon-512", "ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "SLH-DSA-128s"]
    chains = ["Solana", "Bitcoin", "Ethereum"]
    comps = [sol_comp, btc_comp, eth_comp]

    z_values = []
    text_values = []
    for algo in highlight_algos:
        row_z = []
        row_t = []
        for chain_comp in comps:
            analysis = next((a for a in chain_comp.analyses if a.signature_type == algo), None)
            if analysis:
                row_z.append(analysis.relative_to_baseline)
                row_t.append(f"{analysis.relative_to_baseline:.0%}")
            else:
                row_z.append(0)
                row_t.append("N/A")
        z_values.append(row_z)
        text_values.append(row_t)

    fig = go.Figure(data=go.Heatmap(
        z=z_values,
        x=chains,
        y=highlight_algos,
        text=text_values,
        texttemplate="%{text}",
        textfont=dict(size=14),
        colorscale="RdYlGn",
        zmin=0, zmax=1,
        colorbar=dict(title="Retention", tickformat=".0%"),
        hovertemplate="Algorithm: %{y}<br>Chain: %{x}<br>Retention: %{text}<extra></extra>",
    ))
    fig.update_layout(
        title="Throughput Retention by PQC Algorithm & Chain",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
        title_font_size=16,
        yaxis=dict(autorange="reversed"),
        height=350,
    )
    return fig


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
def render(tab, chain_quantum_context: dict) -> None:
    """Render the Overview tab."""
    with tab:
        st.header("PQC & Blockchain: What You Need to Know")
        st.caption("A 30-second primer before you explore the simulator.")

        # ---- Onboarding banner ----
        st.info(
            "This simulator quantifies how replacing classical blockchain signatures "
            "with **post-quantum alternatives** reduces throughput. Start here for context, "
            "then explore the **Algorithms** tab to benchmark PQC schemes, the **Block-Space** "
            "tab for per-chain impact, and the **PQC Shock** tab for Monte Carlo network "
            "simulation results.",
            icon="\U0001f9ed",
        )

        # ---- Two-column intro ----
        intro1, intro2 = st.columns(2)
        with intro1:
            st.subheader("What is PQC?")
            st.markdown(
                "- **Post-quantum cryptography** resists attacks from quantum computers\n"
                "- NIST standardised ML-DSA, SLH-DSA, and Falcon in 2024\n"
                "- PQC signatures are **10x to 700x larger** than classical ones"
            )
        with intro2:
            st.subheader("Why Blockchains?")
            st.markdown(
                "- Every transaction requires a digital signature to prove ownership\n"
                "- Current signatures (Ed25519, ECDSA) are **broken by Shor's algorithm**\n"
                "- Larger PQC signatures directly reduce transactions per block"
            )

        st.divider()
        st.subheader("See the Difference: Classical vs Post-Quantum")
        st.caption("Toggle between classical and PQC to see the impact on a single Solana block.")

        toggle_mode = st.radio(
            "Signature scheme",
            ["Classical (Ed25519)", "Post-Quantum (ML-DSA-65)"],
            horizontal=True,
            key="pqc_toggle",
        )

        # Compute values
        if toggle_mode == "Classical (Ed25519)":
            sig_name = "Ed25519"
            sig_size = 64
            color = "#2ca02c"  # green
        else:
            sig_name = "ML-DSA-65"
            sig_size = 3309  # FIPS 204
            color = "#d62728"  # red

        available_space = int(SOLANA_BLOCK_SIZE_BYTES * 0.30)  # 30% for user txs after votes
        tx_size = SOLANA_BASE_TX_OVERHEAD + sig_size
        txs_per_block = available_space // tx_size
        tps = txs_per_block / (SOLANA_SLOT_TIME_MS / 1000)

        tc1, tc2, tc3, tc4 = st.columns(4)
        with tc1:
            st.metric("Signature Size", f"{sig_size:,} B")
        with tc2:
            st.metric("Transaction Size", f"{tx_size:,} B")
        with tc3:
            st.metric("Txs per Block", f"{txs_per_block:,}")
        with tc4:
            st.metric("Throughput", f"{tps:,.0f} TPS")

        # Show the impact
        if toggle_mode != "Classical (Ed25519)":
            ed_tx = SOLANA_BASE_TX_OVERHEAD + 64
            ed_txs = available_space // ed_tx
            retention = txs_per_block / ed_txs
            st.warning(
                f"Switching from Ed25519 to {sig_name} reduces Solana throughput to "
                f"**{retention:.0%}** of baseline \u2014 a **{(1-retention)*100:.0f}% drop** "
                f"from {ed_txs:,} to {txs_per_block:,} transactions per block. "
                f"Each signature grows from 64 B to {sig_size:,} B ({sig_size//64}\u00d7 larger).",
                icon="\u26a0\ufe0f"
            )
        else:
            st.success(
                "Ed25519 is the current Solana baseline. "
                "Toggle to Post-Quantum to see the throughput impact.",
                icon="\u2705"
            )

        st.divider()

        # ---- Chain Vulnerability at a Glance ----
        st.subheader("Chain Vulnerability at a Glance")

        ov1, ov2, ov3 = st.columns(3)
        for col, (chain_name, ctx) in zip(
            [ov1, ov2, ov3],
            chain_quantum_context.items(),
        ):
            with col:
                st.markdown(f"**{chain_name}**")
                # Use colored circle emoji to approximate brand color
                st.markdown(f"**Current:** {ctx['current_sig']}")
                st.markdown(f"**Threat:** {threat_badge(ctx['quantum_threat'])}")
                st.markdown(f"**Best PQC:** {ctx['recommended_pqc']}")
                st.caption(ctx["recommendation_reason"])

        st.divider()

        # ---- Throughput Retention Heatmap ----
        sol_comp, btc_comp, eth_comp = _get_default_analyses()
        st.subheader("Throughput Retention Heatmap")
        st.caption(
            "Shows what percentage of current throughput each chain retains after "
            "switching to a PQC signature scheme. Solana uses realistic (70% vote overhead) parameters."
        )
        st.plotly_chart(_retention_heatmap(sol_comp, btc_comp, eth_comp), use_container_width=True)
        st.info(
            "**So what?** This heatmap shows the percentage of current throughput each chain "
            "retains after switching to PQC signatures. Green = minimal impact, red = severe. "
            "Notice Falcon-512 stays green across all chains (retaining 80-90%), while SLH-DSA-128s "
            "drops to under 5% on Solana \u2014 meaning 95% of transactions would no longer fit in a block.",
            icon="\U0001f4a1"
        )

        st.divider()

        # ---- Current Baselines ----
        st.subheader("Current Baselines")
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            st.metric("Solana (Ed25519)", f"{sol_comp.baseline.throughput_tps:,.1f} TPS")
            st.caption(f"{sol_comp.baseline.txs_per_block:,} txs/block (70% vote overhead)")
        with bc2:
            st.metric("Bitcoin (ECDSA)", f"{btc_comp.baseline.throughput_tps:,.2f} TPS")
            st.caption(f"{btc_comp.baseline.txs_per_block:,} txs/block (4 MWU, 10 min)")
        with bc3:
            st.metric("Ethereum (ECDSA)", f"{eth_comp.baseline.throughput_tps:,.2f} TPS")
            st.caption(f"{eth_comp.baseline.txs_per_block:,} txs/block (30M gas, 12s)")
        st.info(
            "**So what?** These are the throughput numbers the network achieves today with classical "
            "signatures. Every PQC scheme will reduce these numbers. The question is: by how much?",
            icon="\U0001f4a1"
        )

        st.divider()

        # ---- Best PQC per Chain ----
        st.subheader("Best PQC Option Per Chain")
        for chain_name, chain_comp in [("Solana", sol_comp), ("Bitcoin", btc_comp), ("Ethereum", eth_comp)]:
            best = max(
                [a for a in chain_comp.analyses if a.signature_type != chain_comp.baseline.signature_type],
                key=lambda a: a.txs_per_block,
            )
            worst = min(chain_comp.analyses, key=lambda a: a.txs_per_block)

            with st.expander(f"{chain_name}: Best = {best.signature_type}, Worst = {worst.signature_type}"):
                b1, b2 = st.columns(2)
                with b1:
                    st.markdown(f"**Best PQC: {best.signature_type}**")
                    st.markdown(f"- Retains **{best.relative_to_baseline:.1%}** of baseline throughput")
                    st.markdown(f"- {best.throughput_tps:,.1f} TPS ({best.txs_per_block:,} txs/block)")
                    st.markdown(f"- Signature: {format_bytes(best.signature_bytes)}")
                    st.markdown(f"- Impact: {throughput_impact_category(best.relative_to_baseline)}")
                with b2:
                    st.markdown(f"**Worst PQC: {worst.signature_type}**")
                    st.markdown(f"- Retains **{worst.relative_to_baseline:.1%}** of baseline throughput")
                    st.markdown(f"- {worst.throughput_tps:,.1f} TPS ({worst.txs_per_block:,} txs/block)")
                    st.markdown(f"- Signature: {format_bytes(worst.signature_bytes)}")
                    st.markdown(f"- Impact: {throughput_impact_category(worst.relative_to_baseline)}")

        st.divider()

        # ---- Cross-chain summary note ----
        st.caption(
            "Cross-chain summary uses default parameters for each chain. "
            "Customise per-chain settings in the **Block-Space** tab."
        )

        # ---- Download ----
        cross_dl_rows = []
        for chain_name, chain_comp in [("Solana", sol_comp), ("Bitcoin", btc_comp), ("Ethereum", eth_comp)]:
            for a in chain_comp.analyses:
                cross_dl_rows.append({
                    "Chain": chain_name,
                    "Scheme": a.signature_type,
                    "Signature Bytes": a.signature_bytes,
                    "TX Size Bytes": a.tx_size_bytes,
                    "Txs Per Block": a.txs_per_block,
                    "TPS": a.throughput_tps,
                    "Relative to Baseline": a.relative_to_baseline,
                    "Signature Overhead Pct": a.signature_overhead_pct,
                })
        st.download_button(
            "Download Cross-Chain Summary CSV",
            pd.DataFrame(cross_dl_rows).to_csv(index=False),
            "cross_chain_pqc_summary.csv",
            "text/csv",
            key="dl_crosschain",
        )
