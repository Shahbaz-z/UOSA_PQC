"""Tab 1: Block-Space Visualizer -- per-chain throughput impact analysis."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from blockchain.chain_models import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SIGNATURE_SIZES,
    SOLANA_BLOCK_SIZE_BYTES, SOLANA_BASE_TX_OVERHEAD, SOLANA_SLOT_TIME_MS,
    BITCOIN_BLOCK_WEIGHT_LIMIT, BITCOIN_BASE_TX_OVERHEAD, BITCOIN_BLOCK_TIME_MS,
    ETHEREUM_BLOCK_GAS_LIMIT, ETHEREUM_BASE_TX_OVERHEAD, ETHEREUM_BLOCK_TIME_MS,
    ETHEREUM_GAS_LIMITS,
)
from app.components.charts import (
    block_space_chart,
    throughput_comparison_chart,
    signature_size_comparison,
)


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


def _threat_badge(level: str) -> str:
    """Return a colored threat level badge in markdown."""
    colors = {"HIGH": "red", "MODERATE-HIGH": "orange", "MODERATE": "orange", "LOW": "green"}
    return f":{colors.get(level, 'gray')}[**{level}**]"


def _format_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1024:
        return f"{n:,} B ({n / 1024:.1f} KB)"
    return f"{n:,} B"


def render(tab, chain_quantum_context: dict) -> None:
    """Render the Block-Space Visualizer tab."""
    with tab:
        st.header("Block-Space Impact Analysis")
        st.caption(
            "Explore how replacing classical signatures with PQC alternatives affects "
            "blockchain transaction throughput."
        )

        chain = st.radio(
            "Select blockchain",
            ["Solana", "Bitcoin", "Ethereum"],
            horizontal=True,
            key="chain_select",
            help="Each blockchain has different block structure and size limits.",
        )

        # ---- Quantum Vulnerability Assessment (per-chain) ----
        ctx = chain_quantum_context[chain]
        with st.expander(f"Quantum Vulnerability Assessment: {chain}", expanded=True):
            vc1, vc2 = st.columns([1, 1])
            with vc1:
                st.markdown(f"**Current Signature:** {ctx['current_sig']}")
                st.markdown(f"**Quantum Threat Level:** {_threat_badge(ctx['quantum_threat'])}")
                st.markdown(ctx["threat_detail"])
            with vc2:
                st.markdown("**Migration Challenge:**")
                st.markdown(ctx["migration_challenge"])
                st.markdown(f"**Recommended PQC:** {ctx['recommended_pqc']}")
                st.caption(ctx["recommendation_reason"])

        # Multi-signer control (shared across all chains)
        num_signers = st.slider(
            "Number of signers per transaction",
            min_value=1, max_value=5, value=1,
            key="num_signers",
            help="Multi-signature transactions multiply signature and public key sizes. "
                 "E.g. a 3-signer ML-DSA-65 tx has ~10 KB of signatures alone.",
        )

        if chain == "Solana":
            comp = _render_solana_section(num_signers)
        elif chain == "Bitcoin":
            comp = _render_bitcoin_section(num_signers)
        else:
            comp = _render_ethereum_section(num_signers)

        # Charts and key findings (below the params/results columns)
        _render_charts_and_findings(comp, chain)


def _render_solana_section(num_signers: int):
    """Render Solana parameters + results table; return comparison."""
    with st.expander("About the Solana model"):
        st.markdown(
            "**Solana** uses Ed25519 signatures (64 bytes) with ~6 MB practical "
            "block size and 400 ms slot times.\n\n"
            "This model calculates how many transactions fit per block when "
            "the signature scheme changes. Larger PQC signatures mean fewer "
            "transactions per block and lower throughput.\n\n"
            "**Vote Transaction Overhead:** In reality, 70-80% of Solana block space "
            "is consumed by validator vote transactions. Use the vote overhead slider "
            "to model realistic vs theoretical capacity."
        )

    st.markdown("##### Quick Presets")
    pc1, pc2, pc3, pc4 = st.columns(4)
    with pc1:
        if st.button("Theoretical Max", key="sol_theoretical", use_container_width=True,
                     help="100% for user txs (no vote overhead)"):
            st.session_state["sol_block_size"] = SOLANA_BLOCK_SIZE_BYTES
            st.session_state["sol_base_overhead"] = SOLANA_BASE_TX_OVERHEAD
            st.session_state["sol_slot_time"] = SOLANA_SLOT_TIME_MS
            st.session_state["sol_vote_pct"] = 0
            st.rerun()
    with pc2:
        if st.button("Realistic (70%)", key="sol_realistic", use_container_width=True,
                     help="70% vote overhead (30% for user txs)"):
            st.session_state["sol_block_size"] = SOLANA_BLOCK_SIZE_BYTES
            st.session_state["sol_base_overhead"] = SOLANA_BASE_TX_OVERHEAD
            st.session_state["sol_slot_time"] = SOLANA_SLOT_TIME_MS
            st.session_state["sol_vote_pct"] = 70
            st.rerun()
    with pc3:
        if st.button("High Activity", key="sol_high_activity", use_container_width=True,
                     help="80% vote overhead (20% for user txs)"):
            st.session_state["sol_block_size"] = SOLANA_BLOCK_SIZE_BYTES
            st.session_state["sol_base_overhead"] = SOLANA_BASE_TX_OVERHEAD
            st.session_state["sol_slot_time"] = SOLANA_SLOT_TIME_MS
            st.session_state["sol_vote_pct"] = 80
            st.rerun()
    with pc4:
        if st.button("High Throughput", key="sol_high", use_container_width=True,
                     help="12 MB block, no vote overhead"):
            st.session_state["sol_block_size"] = 12_000_000
            st.session_state["sol_base_overhead"] = 200
            st.session_state["sol_slot_time"] = SOLANA_SLOT_TIME_MS
            st.session_state["sol_vote_pct"] = 0
            st.rerun()

    col_params, col_results = st.columns([1, 2])

    with col_params:
        st.markdown("##### Model Parameters")
        vote_pct = st.slider(
            "Vote transaction overhead (%)",
            min_value=0, max_value=85,
            value=st.session_state.get("sol_vote_pct", 0),
            step=5, key="sol_vote_pct",
            help="70-80% of Solana blocks are validator votes. Set to 0 for theoretical max.",
        )
        block_size = st.number_input(
            "Block size (bytes)",
            value=st.session_state.get("sol_block_size", SOLANA_BLOCK_SIZE_BYTES),
            min_value=100_000, max_value=50_000_000, step=1_000_000,
            key="sol_block_size",
            help="Solana practical block size (~6 MB default, theoretical max 32 MB)",
        )
        base_overhead = st.number_input(
            "Base tx overhead (bytes)",
            value=st.session_state.get("sol_base_overhead", SOLANA_BASE_TX_OVERHEAD),
            min_value=50, max_value=2000, step=10,
            key="sol_base_overhead",
            help="Transaction overhead excluding the signature (accounts, instructions, blockhash)",
        )
        slot_time = st.number_input(
            "Slot time (ms)",
            value=st.session_state.get("sol_slot_time", SOLANA_SLOT_TIME_MS),
            min_value=100, max_value=2000, step=50,
            key="sol_slot_time",
            help="Target time per slot (400 ms default)",
        )
        if vote_pct > 0:
            st.caption(f"Available for user txs: {100 - vote_pct}% ({int(block_size * (100 - vote_pct) / 100):,} bytes)")

    comp = compare_all_solana(block_size, base_overhead, slot_time,
                              num_signers=num_signers, vote_tx_pct=vote_pct / 100)

    with col_results:
        _render_results_table(comp, "solana", num_signers)

    return comp


def _render_bitcoin_section(num_signers: int):
    """Render Bitcoin parameters + results table; return comparison."""
    with st.expander("About the Bitcoin model"):
        st.markdown(
            "**Bitcoin** uses ECDSA (secp256k1) signatures with a 4 MWU block weight "
            "limit and 10-minute block times.\n\n"
            "**SegWit discount (BIP 141):** Witness data (signatures + public keys) "
            "counts at **1/4 weight**, while non-witness data counts at full weight. "
            "This partially offsets the size increase of PQC signatures.\n\n"
            "**Example:** A 3,293-byte ML-DSA-65 signature costs 3,293 weight units "
            "under SegWit, compared to 13,172 WU without the discount."
        )

    st.markdown("##### Quick Presets")
    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        if st.button("Default Bitcoin", key="btc_default", use_container_width=True,
                     help="4 MWU, 150 B overhead, 10 min blocks"):
            st.session_state["btc_block_weight"] = BITCOIN_BLOCK_WEIGHT_LIMIT
            st.session_state["btc_base_overhead"] = BITCOIN_BASE_TX_OVERHEAD
            st.session_state["btc_block_time"] = BITCOIN_BLOCK_TIME_MS
            st.rerun()
    with pc2:
        if st.button("Larger Blocks", key="btc_large", use_container_width=True,
                     help="8 MWU, 150 B overhead, 10 min blocks"):
            st.session_state["btc_block_weight"] = 8_000_000
            st.session_state["btc_base_overhead"] = 150
            st.session_state["btc_block_time"] = BITCOIN_BLOCK_TIME_MS
            st.rerun()
    with pc3:
        if st.button("Faster Blocks", key="btc_fast", use_container_width=True,
                     help="4 MWU, 150 B overhead, 2.5 min blocks"):
            st.session_state["btc_block_weight"] = 4_000_000
            st.session_state["btc_base_overhead"] = 150
            st.session_state["btc_block_time"] = 150_000
            st.rerun()

    col_params, col_results = st.columns([1, 2])

    with col_params:
        st.markdown("##### Model Parameters")
        block_weight = st.number_input(
            "Block weight limit (WU)",
            value=st.session_state.get("btc_block_weight", BITCOIN_BLOCK_WEIGHT_LIMIT),
            min_value=100_000, max_value=16_000_000, step=1_000_000,
            key="btc_block_weight",
            help="BIP 141 weight limit (4,000,000 WU = 4 MWU default)",
        )
        btc_base_overhead = st.number_input(
            "Base tx overhead (bytes)",
            value=st.session_state.get("btc_base_overhead", BITCOIN_BASE_TX_OVERHEAD),
            min_value=50, max_value=1000, step=10,
            key="btc_base_overhead",
            help="Non-witness transaction overhead (version, locktime, I/O)",
        )
        block_time = st.number_input(
            "Block time (ms)",
            value=st.session_state.get("btc_block_time", BITCOIN_BLOCK_TIME_MS),
            min_value=10_000, max_value=3_600_000, step=60_000,
            key="btc_block_time",
            help="Average time between blocks (600,000 ms = 10 min default)",
        )

    comp = compare_all_bitcoin(block_weight, btc_base_overhead, block_time,
                               num_signers=num_signers)

    with col_results:
        _render_results_table(comp, "bitcoin", num_signers)

    return comp


def _render_ethereum_section(num_signers: int):
    """Render Ethereum parameters + results table; return comparison."""
    with st.expander("About the Ethereum model"):
        st.markdown(
            "**Ethereum** uses ECDSA (secp256k1) signatures with a gas-based cost model.\n\n"
            "Unlike Solana and Bitcoin, Ethereum block capacity is measured in **gas** "
            "rather than bytes. Each transaction pays:\n"
            "- **21,000 gas** base intrinsic cost\n"
            "- **16 gas per non-zero byte** of calldata (signature + public key)\n\n"
            "**2026 Gas Limit Increases:** Ethereum is increasing block gas limits from "
            "30M (2024) to potentially 180M by late 2026. Use presets to model future capacity."
        )

    st.markdown("##### Gas Limit Presets (2024-2026)")
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    with pc1:
        if st.button("30M (2024)", key="eth_2024", use_container_width=True,
                     help="2024 baseline: 30M gas"):
            st.session_state["eth_gas_limit"] = ETHEREUM_GAS_LIMITS["2024_baseline"]
            st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
            st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
            st.rerun()
    with pc2:
        if st.button("36M (2025)", key="eth_2025", use_container_width=True,
                     help="2025 current: 36M gas"):
            st.session_state["eth_gas_limit"] = ETHEREUM_GAS_LIMITS["2025_current"]
            st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
            st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
            st.rerun()
    with pc3:
        if st.button("60M (Q1 2026)", key="eth_2026_q1", use_container_width=True,
                     help="2026 Q1 target: 60M gas"):
            st.session_state["eth_gas_limit"] = ETHEREUM_GAS_LIMITS["2026_q1"]
            st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
            st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
            st.rerun()
    with pc4:
        if st.button("80M (Q2 2026)", key="eth_2026_q2", use_container_width=True,
                     help="2026 Q2 target: 80M gas"):
            st.session_state["eth_gas_limit"] = ETHEREUM_GAS_LIMITS["2026_q2"]
            st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
            st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
            st.rerun()
    with pc5:
        if st.button("180M (Target)", key="eth_target", use_container_width=True,
                     help="2026 target: 180M gas"):
            st.session_state["eth_gas_limit"] = ETHEREUM_GAS_LIMITS["2026_target"]
            st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
            st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
            st.rerun()

    col_params, col_results = st.columns([1, 2])

    with col_params:
        st.markdown("##### Model Parameters")
        eth_gas_limit = st.number_input(
            "Block gas limit",
            value=st.session_state.get("eth_gas_limit", ETHEREUM_BLOCK_GAS_LIMIT),
            min_value=1_000_000, max_value=200_000_000, step=5_000_000,
            key="eth_gas_limit",
            help="Ethereum block gas limit (30M baseline, up to 180M by 2026)",
        )
        eth_base_overhead = st.number_input(
            "Base tx overhead (bytes)",
            value=st.session_state.get("eth_base_overhead", ETHEREUM_BASE_TX_OVERHEAD),
            min_value=50, max_value=500, step=10,
            key="eth_base_overhead",
            help="Non-signature calldata overhead (to, value, nonce, etc.)",
        )
        eth_block_time = st.number_input(
            "Block time (ms)",
            value=st.session_state.get("eth_block_time", ETHEREUM_BLOCK_TIME_MS),
            min_value=1_000, max_value=60_000, step=1_000,
            key="eth_block_time",
            help="Slot time (12,000 ms = 12s default, post-Merge)",
        )

    comp = compare_all_ethereum(eth_gas_limit, eth_base_overhead, eth_block_time,
                                num_signers=num_signers)

    with col_results:
        _render_results_table(comp, "ethereum", num_signers)

    return comp


def _render_results_table(comp, chain_key: str, num_signers: int) -> None:
    """Render the results summary table and CSV download inside a column context."""
    st.markdown("##### Results Summary")
    if num_signers > 1:
        st.caption(f"Modeling **{num_signers} signers** per transaction")
    summary_rows = []
    for a in comp.analyses:
        if a.relative_to_baseline >= 0.9:
            impact = "Minimal"
        elif a.relative_to_baseline >= 0.7:
            impact = "Moderate"
        elif a.relative_to_baseline >= 0.4:
            impact = "Significant"
        else:
            impact = "Severe"
        summary_rows.append({
            "Scheme": a.signature_type,
            "Sig Size (B)": f"{a.signature_bytes:,}",
            "Tx Size (B)": f"{a.tx_size_bytes:,}",
            "Txs/Block": f"{a.txs_per_block:,}",
            "TPS": f"{a.throughput_tps:,.1f}",
            "vs Baseline": f"{a.relative_to_baseline:.1%}",
            "Impact": impact,
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    csv_data = pd.DataFrame([
        {
            "Scheme": a.signature_type,
            "Signature Bytes": a.signature_bytes,
            "TX Size Bytes": a.tx_size_bytes,
            "Txs Per Block": a.txs_per_block,
            "TPS": a.throughput_tps,
            "Relative to Baseline": a.relative_to_baseline,
            "Signature Overhead Pct": a.signature_overhead_pct,
        }
        for a in comp.analyses
    ])
    st.download_button(
        "Download Results CSV",
        csv_data.to_csv(index=False),
        f"{chain_key}_block_space_analysis.csv",
        "text/csv",
        key=f"dl_{chain_key}_results",
    )


def _render_charts_and_findings(comp, chain: str) -> None:
    """Render charts and key findings below the params/results section."""
    st.divider()

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.plotly_chart(block_space_chart(comp.analyses, chain), use_container_width=True)
    with chart_col2:
        st.plotly_chart(throughput_comparison_chart(comp.analyses, chain), use_container_width=True)

    st.plotly_chart(signature_size_comparison(comp.analyses, chain), use_container_width=True)

    # Key findings
    st.divider()
    st.subheader("Key Findings")
    baseline = comp.baseline
    worst = min(comp.analyses, key=lambda a: a.txs_per_block)
    best_pqc = max(
        [a for a in comp.analyses if a.signature_type != baseline.signature_type],
        key=lambda a: a.txs_per_block,
    )
    falcon_size = SIGNATURE_SIZES["Falcon-512"]
    mldsa_size = SIGNATURE_SIZES["ML-DSA-44"]
    falcon_ratio = round(mldsa_size / falcon_size, 1)

    kf1, kf2, kf3 = st.columns(3)
    with kf1:
        st.metric(
            f"{baseline.signature_type} Baseline",
            f"{baseline.txs_per_block:,} txs/block",
            help="Current transaction capacity with the chain's default signature scheme",
        )
        st.caption(f"{baseline.throughput_tps:,.1f} TPS")
    with kf2:
        st.metric(
            f"Best PQC: {best_pqc.signature_type}",
            f"{best_pqc.txs_per_block:,} txs/block",
            delta=f"{best_pqc.relative_to_baseline:.1%} of baseline",
            delta_color="inverse" if best_pqc.relative_to_baseline < 1 else "normal",
        )
        st.caption(f"{best_pqc.throughput_tps:,.1f} TPS | {_throughput_impact_category(best_pqc.relative_to_baseline)}")
    with kf3:
        st.metric(
            f"Worst: {worst.signature_type}",
            f"{worst.txs_per_block:,} txs/block",
            delta=f"{worst.relative_to_baseline:.1%} of baseline",
            delta_color="inverse",
        )
        st.caption(f"{worst.throughput_tps:,.1f} TPS | {_throughput_impact_category(worst.relative_to_baseline)}")

    st.info(
        f"Falcon-512 signatures (**{falcon_size} B**) are **{falcon_ratio}x smaller** "
        f"than ML-DSA-44 (**{mldsa_size:,} B**), making Falcon the most block-space "
        "efficient PQC signature scheme for blockchain applications.",
        icon="💡",
    )

    # Model Assumptions
    st.divider()
    with st.expander("Model Assumptions & Limitations"):
        st.markdown(
            "**What this model captures:**\n"
            "- Signature and public key contribution to transaction size\n"
            "- Block capacity limits (bytes for Solana, weight for Bitcoin, gas for Ethereum)\n"
            "- SegWit witness discount for Bitcoin (1/4 weight for witness data)\n"
            "- Gas-based calldata costing for Ethereum (16 gas per non-zero byte)\n"
            "- Vote transaction overhead for Solana (configurable 0-85%)\n"
            "- Multi-signer transactions (1-5 signers)\n\n"
            "**What this model does NOT capture:**\n"
            "- Verification time impact on block processing\n"
            "- Network propagation delays from larger transactions\n"
            "- Smart contract execution gas costs (Ethereum)\n"
            "- Memory and storage costs for nodes\n"
            "- Actual transaction mix (DEX swaps, token transfers, etc.)\n"
            "- Compression techniques that could reduce PQC signature sizes\n"
            "- Signature aggregation schemes (e.g., BLS aggregation)\n\n"
            "**Sources:**\n"
            "- NIST FIPS 203/204/205 for algorithm parameter sizes\n"
            "- Solana docs for block structure and vote transaction estimates\n"
            "- Bitcoin BIP 141 for SegWit witness discount rules\n"
            "- Ethereum Yellow Paper for gas cost model\n"
            "- Ethereum core dev discussions for 2024-2026 gas limit roadmap"
        )
