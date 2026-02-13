"""Tab 3: Cross-Chain Summary -- compare PQC impact across all three blockchains."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from blockchain.chain_models import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SIGNATURE_SIZES,
    SOLANA_VOTE_TX_PCT_REALISTIC,
)


def _threat_badge(level: str) -> str:
    """Return a colored threat level badge in markdown."""
    colors = {"HIGH": "red", "MODERATE-HIGH": "orange", "MODERATE": "orange", "LOW": "green"}
    return f":{colors.get(level, 'gray')}[**{level}**]"


def _format_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1024:
        return f"{n:,} B ({n / 1024:.1f} KB)"
    return f"{n:,} B"


def _throughput_impact_category(ratio: float) -> str:
    """Categorize throughput impact for educational display."""
    if ratio >= 0.9:
        return ":green[Minimal Impact]"
    elif ratio >= 0.7:
        return ":orange[Moderate Impact]"
    elif ratio >= 0.4:
        return ":red[Significant Impact]"
    else:
        return ":red[Severe Impact]"


def render(tab, chain_quantum_context: dict) -> None:
    """Render the Cross-Chain Summary tab."""
    with tab:
        st.header("Cross-Chain PQC Impact Summary")
        st.caption(
            "Compare the impact of PQC migration across Solana, Bitcoin, and Ethereum "
            "using default parameters for each chain."
        )

        # Run all three chain analyses with defaults
        sol_comp = compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC)
        btc_comp = compare_all_bitcoin()
        eth_comp = compare_all_ethereum()

        # Key PQC algorithms to highlight
        highlight_algos = ["Falcon-512", "ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "SLH-DSA-128s"]

        # Vulnerability overview
        st.subheader("Quantum Vulnerability Overview")
        ov1, ov2, ov3 = st.columns(3)
        for col, (chain_name, ctx) in zip(
            [ov1, ov2, ov3],
            chain_quantum_context.items(),
        ):
            with col:
                st.markdown(f"### {chain_name}")
                st.markdown(f"**Current:** {ctx['current_sig']}")
                st.markdown(f"**Threat:** {_threat_badge(ctx['quantum_threat'])}")
                st.markdown(f"**Best PQC:** {ctx['recommended_pqc']}")
                st.caption(ctx["recommendation_reason"])

        st.divider()

        # Cross-chain comparison table
        st.subheader("Throughput Retention by PQC Algorithm")
        st.caption(
            "Shows what percentage of current throughput each chain retains after "
            "switching to a PQC signature scheme. Solana uses realistic (70% vote overhead) parameters."
        )

        cross_rows = []
        for algo in highlight_algos:
            row = {"Algorithm": algo, "Sig Size (B)": f"{SIGNATURE_SIZES[algo]:,}"}

            sol_analysis = next((a for a in sol_comp.analyses if a.signature_type == algo), None)
            if sol_analysis:
                row["Solana TPS"] = f"{sol_analysis.throughput_tps:,.1f}"
                row["Solana Retention"] = f"{sol_analysis.relative_to_baseline:.1%}"
            else:
                row["Solana TPS"] = "N/A"
                row["Solana Retention"] = "N/A"

            btc_analysis = next((a for a in btc_comp.analyses if a.signature_type == algo), None)
            if btc_analysis:
                row["Bitcoin TPS"] = f"{btc_analysis.throughput_tps:,.2f}"
                row["Bitcoin Retention"] = f"{btc_analysis.relative_to_baseline:.1%}"
            else:
                row["Bitcoin TPS"] = "N/A"
                row["Bitcoin Retention"] = "N/A"

            eth_analysis = next((a for a in eth_comp.analyses if a.signature_type == algo), None)
            if eth_analysis:
                row["Ethereum TPS"] = f"{eth_analysis.throughput_tps:,.2f}"
                row["Ethereum Retention"] = f"{eth_analysis.relative_to_baseline:.1%}"
            else:
                row["Ethereum TPS"] = "N/A"
                row["Ethereum Retention"] = "N/A"

            cross_rows.append(row)

        st.dataframe(pd.DataFrame(cross_rows), use_container_width=True, hide_index=True)

        # Baseline comparison
        st.divider()
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

        # Best PQC per chain
        st.divider()
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
                    st.markdown(f"- Signature: {_format_bytes(best.signature_bytes)}")
                    st.markdown(f"- Impact: {_throughput_impact_category(best.relative_to_baseline)}")
                with b2:
                    st.markdown(f"**Worst PQC: {worst.signature_type}**")
                    st.markdown(f"- Retains **{worst.relative_to_baseline:.1%}** of baseline throughput")
                    st.markdown(f"- {worst.throughput_tps:,.1f} TPS ({worst.txs_per_block:,} txs/block)")
                    st.markdown(f"- Signature: {_format_bytes(worst.signature_bytes)}")
                    st.markdown(f"- Impact: {_throughput_impact_category(worst.relative_to_baseline)}")

        # Download cross-chain summary
        st.divider()
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
