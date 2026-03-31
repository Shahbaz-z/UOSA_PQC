"""Tab 2: Chain Architecture — per-chain accurate capacity models.

Shows:
  - Bitcoin: UTXO vulnerability distribution (P2PK/P2PKH/P2WPKH/P2TR by BTC)
  - Ethereum: PQC gas schedule table (classical vs each PQC algo)
  - Solana: Vote transaction overhead (stacked bar: vote vs user space per algo)
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
from simulator.chains.bitcoin_vulnerability import (
    DEFAULT_UTXO_DISTRIBUTION,
    DEFAULT_EXPOSURE_MODEL,
    ADDRESS_VULNERABILITY,
    AddressTypeVulnerability,
)
from simulator.chains.ethereum_specific import (
    PQC_VERIFICATION_GAS,
    EthereumTxModel,
)
from simulator.chains.solana_specific import (
    DEFAULT_SOLANA_TX_MODEL,
    CU_COSTS,
    BLOCK_COMPUTE_UNIT_LIMIT,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

VULN_COLORS: dict = {
    AddressTypeVulnerability.CRITICAL:   "#FF3B3B",
    AddressTypeVulnerability.HIGH:       "#FF7E3B",
    AddressTypeVulnerability.MEDIUM:     "#FFB23B",
    AddressTypeVulnerability.MEDIUM_LOW: "#FFE03B",
    AddressTypeVulnerability.LOW:        "#6BE56B",
    AddressTypeVulnerability.UNKNOWN:    "#AAAAAA",
}

ALGO_COLORS: dict = {
    "ECDSA": "#6c8ebf",
    "Ed25519": "#6c8ebf",
    "ML-DSA-44": "#a8d5a2",
    "ML-DSA-65": "#4caf50",
    "ML-DSA-87": "#1b5e20",
    "Falcon-512": "#ffd54f",
    "Falcon-1024": "#ff8f00",
    "SLH-DSA-128s": "#ef9a9a",
    "SLH-DSA-128f": "#e53935",
}


@st.cache_data(show_spinner=False)
def _bitcoin_utxo_chart():
    """Build the Bitcoin UTXO vulnerability pie chart."""
    dist = DEFAULT_UTXO_DISTRIBUTION
    labels, values, colors, hover = [], [], [], []

    for addr_type, btc in dist.btc_by_type.items():
        vuln = ADDRESS_VULNERABILITY.get(addr_type, AddressTypeVulnerability.UNKNOWN)
        labels.append(f"{addr_type}<br>({btc/1e6:.1f}M BTC)")
        values.append(btc)
        colors.append(VULN_COLORS.get(vuln, "#AAAAAA"))
        hover.append(
            f"{addr_type}: {btc/1e6:.2f}M BTC<br>"
            f"Vulnerability: {vuln.value.upper()}<br>"
            f"Fraction: {100 * btc / dist.total_btc:.1f}%"
        )

    fig = go.Figure(data=[go.Pie(
        labels      = labels,
        values      = values,
        marker      = dict(colors=colors, line=dict(color="white", width=2)),
        hovertext   = hover,
        hoverinfo   = "text",
        textinfo    = "label+percent",
        hole        = 0.4,
    )])
    fig.update_layout(
        title       = "Bitcoin UTXO Set by Address Type — Quantum Exposure",
        showlegend  = False,
        height      = 450,
        margin      = dict(l=20, r=20, t=60, b=20),
    )
    return fig


@st.cache_data(show_spinner=False)
def _bitcoin_exposure_timeline():
    """Build the BTC at risk over time chart."""
    model  = DEFAULT_EXPOSURE_MODEL
    tl     = model.exposure_timeline(years=15)
    years  = [v["calendar_year"] for v in tl.values()]
    imm    = [v["immediate_btc"]  / 1e6 for v in tl.values()]
    defd   = [v["cumulative_deferred_btc"] / 1e6 for v in tl.values()]
    crqc_p = [v["crqc_probability"] * 100 for v in tl.values()]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=imm,
        name="Immediate (P2PK)",
        fill="tozeroy",
        line=dict(color="#FF3B3B", width=2),
        hovertemplate="%{y:.2f}M BTC<extra>Immediate Exposure</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=[a + b for a, b in zip(imm, defd)],
        name="+ Deferred (P2PKH/P2WPKH/P2WSH)",
        fill="tonexty",
        line=dict(color="#FF7E3B", width=2),
        hovertemplate="%{y:.2f}M BTC total<extra>Total Vulnerable</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=crqc_p,
        name="CRQC Probability (%)",
        yaxis="y2",
        line=dict(color="#9945FF", dash="dash", width=2),
        hovertemplate="%{y:.1f}%<extra>CRQC Probability</extra>",
    ))
    fig.update_layout(
        title   = "BTC at Risk Over Time (Mosca's Inequality Framework)",
        xaxis   = dict(title="Year"),
        yaxis   = dict(title="BTC Exposed (millions)", tickformat=".1f"),
        yaxis2  = dict(title="CRQC Probability (%)", overlaying="y", side="right",
                       range=[0, 100], tickformat=".0f"),
        legend  = dict(x=0.01, y=0.99),
        height  = 400,
        hovermode="x unified",
    )
    return fig


@st.cache_data(show_spinner=False)
def _ethereum_gas_table():
    """Build the Ethereum PQC gas schedule DataFrame."""
    model = EthereumTxModel()
    rows  = []
    algos = [
        "ECDSA", "Ed25519",
        "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
        "Falcon-512", "Falcon-1024",
        "SLH-DSA-128s", "SLH-DSA-128f",
    ]
    ecdsa_gas = PQC_VERIFICATION_GAS["ECDSA"]
    ecdsa_txs = model.txs_per_block(
        SIGNATURE_SIZES.get("ECDSA", 72),
        PUBLIC_KEY_SIZES.get("ECDSA", 33),
        sig_algorithm="ECDSA",
    )

    for algo in algos:
        sig_sz = SIGNATURE_SIZES.get(algo, 64)
        pk_sz  = PUBLIC_KEY_SIZES.get(algo, 32)
        vgas   = PQC_VERIFICATION_GAS.get(algo, 3_000)
        txs    = model.txs_per_block(sig_sz, pk_sz, sig_algorithm=algo)
        total_gas = model.tx_gas(sig_sz, pk_sz, sig_algorithm=algo)
        rows.append({
            "Algorithm":         algo,
            "Sig + PK Size (B)": sig_sz + pk_sz,
            "Verify Gas":        f"{vgas:,}",
            "Total Tx Gas":      f"{total_gas:,}",
            "Gas vs ECDSA":      f"{vgas / ecdsa_gas:.0f}×",
            "Max Txs/Block":     f"{txs:,}",
            "Txs vs ECDSA":      f"{txs / ecdsa_txs:.2f}×",
        })

    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _ethereum_gas_bar():
    """Verification gas bar chart for Ethereum."""
    algos = [
        "ECDSA", "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
        "Falcon-512", "Falcon-1024", "SLH-DSA-128s", "SLH-DSA-128f",
    ]
    gas_vals = [PQC_VERIFICATION_GAS.get(a, 3_000) for a in algos]
    colors   = [ALGO_COLORS.get(a, "#aaa") for a in algos]

    fig = go.Figure(go.Bar(
        x           = algos,
        y           = gas_vals,
        marker_color= colors,
        text        = [f"{g:,}" for g in gas_vals],
        textposition= "outside",
        hovertemplate="%{x}<br>Verify Gas: %{y:,}<extra></extra>",
    ))
    fig.add_hline(
        y=3_000, line_dash="dash", line_color="grey",
        annotation_text="ECDSA ecRecover (3,000 gas)",
        annotation_position="top right",
    )
    fig.update_layout(
        title  = "Ethereum PQC Signature Verification Gas Cost",
        yaxis  = dict(title="Gas (log scale)", type="log"),
        xaxis  = dict(title="Algorithm"),
        height = 420,
    )
    return fig


@st.cache_data(show_spinner=False)
def _solana_vote_overhead_chart():
    """Stacked bar: vote vs user space per algorithm in a Solana block."""
    algos = [
        "Ed25519", "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
        "Falcon-512", "Falcon-1024", "SLH-DSA-128s", "SLH-DSA-128f",
    ]
    model = DEFAULT_SOLANA_TX_MODEL
    vote_bytes, user_bytes, saturated = [], [], []

    for algo in algos:
        cap   = model.block_capacity_analysis(algo)
        vb    = min(cap["vote_tx_bytes_total"], model.block_size_bytes)
        ub    = cap["user_tx_capacity_bytes"]
        vote_bytes.append(vb / 1e6)
        user_bytes.append(ub / 1e6)
        saturated.append(cap["is_vote_saturated"])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Vote Transactions",
        x   = algos,
        y   = vote_bytes,
        marker_color = "#9945FF",
        hovertemplate="%{x}<br>Vote bytes: %{y:.2f} MB<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="User Tx Capacity",
        x   = algos,
        y   = user_bytes,
        marker_color = "#4caf50",
        hovertemplate="%{x}<br>User capacity: %{y:.2f} MB<extra></extra>",
    ))

    # Mark saturated bars
    for i, (algo, sat) in enumerate(zip(algos, saturated)):
        if sat:
            fig.add_annotation(
                x=algo, y=model.block_size_bytes / 1e6 + 0.2,
                text="⛔ SATURATED", showarrow=False,
                font=dict(color="red", size=10),
            )

    fig.add_hline(
        y=model.block_size_bytes / 1e6,
        line_dash="dash", line_color="red",
        annotation_text="Block limit (6 MB)",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode = "stack",
        title   = "Solana Block Space: Vote vs User Transaction Capacity by Algorithm",
        yaxis   = dict(title="Block Space (MB)"),
        xaxis   = dict(title="Signature Algorithm"),
        legend  = dict(x=0.6, y=0.99),
        height  = 450,
    )
    return fig


@st.cache_data(show_spinner=False)
def _solana_cu_chart():
    """Solana compute unit usage: votes vs block limit."""
    algos   = ["Ed25519", "ML-DSA-65", "Falcon-512", "SLH-DSA-128s", "SLH-DSA-128f"]
    model   = DEFAULT_SOLANA_TX_MODEL
    cu_vals = []
    labels  = []
    colors  = []

    for algo in algos:
        cap = model.block_capacity_analysis(algo)
        cu_vals.append(cap["compute_unit_total_votes"] / 1e6)
        labels.append(algo)
        colors.append("#FF3B3B" if cap["is_cu_saturated"] else "#4caf50")

    fig = go.Figure(go.Bar(
        x           = labels,
        y           = cu_vals,
        marker_color= colors,
        text        = [f"{v:.0f}M CU" for v in cu_vals],
        textposition= "outside",
    ))
    fig.add_hline(
        y=BLOCK_COMPUTE_UNIT_LIMIT / 1e6,
        line_dash="dash", line_color="red",
        annotation_text="Block CU limit (48M)",
    )
    fig.update_layout(
        title  = "Solana: Vote Transaction Compute Units vs Block Limit",
        yaxis  = dict(title="Compute Units (millions)"),
        height = 380,
    )
    return fig


def render(tab):
    """Render the Chain Architecture tab."""
    with tab:
        st.header("Chain Architecture")
        st.caption(
            "Per-chain accurate capacity models showing how PQC affects "
            "Bitcoin's UTXO vulnerability, Ethereum's gas economics, and "
            "Solana's vote transaction overhead."
        )

        btc_tab, eth_tab, sol_tab = st.tabs(["₿ Bitcoin", "Ξ Ethereum", "◎ Solana"])

        # ------------------------------------------------------------------
        # Bitcoin
        # ------------------------------------------------------------------
        with btc_tab:
            st.subheader("Bitcoin UTXO Quantum Vulnerability")
            st.markdown(
                "Bitcoin's PQC risk is stratified by **address type**. P2PK outputs "
                "expose the public key directly on-chain — a CRQC can steal these coins "
                "without waiting for the owner to transact."
            )

            col1, col2 = st.columns([1, 1])
            with col1:
                st.plotly_chart(_bitcoin_utxo_chart(), use_container_width=True)
            with col2:
                # Vulnerability legend
                dist = DEFAULT_UTXO_DISTRIBUTION
                model = DEFAULT_EXPOSURE_MODEL
                st.markdown("### Vulnerability Summary")
                for addr_type in ["P2PK", "P2PKH", "P2WPKH", "P2WSH", "P2SH", "P2TR"]:
                    vuln = ADDRESS_VULNERABILITY.get(addr_type)
                    btc  = dist.btc_by_type.get(addr_type, 0)
                    c    = VULN_COLORS.get(vuln, "#aaa")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;margin-bottom:4px'>"
                        f"<div style='width:14px;height:14px;background:{c};border-radius:3px;"
                        f"margin-right:8px'></div>"
                        f"<b>{addr_type}</b>&nbsp;—&nbsp;{btc/1e6:.2f}M BTC "
                        f"({vuln.value.upper() if vuln else 'UNKNOWN'})</div>",
                        unsafe_allow_html=True,
                    )

                st.markdown("---")
                st.metric("Immediate Exposure (P2PK)", f"{model.immediate_exposure_btc()/1e6:.1f}M BTC",
                          help="Vulnerable today without any new transaction")
                st.metric("Deferred Exposure", f"{model.deferred_exposure_btc()/1e6:.1f}M BTC",
                          help="Vulnerable only when next spent")
                st.metric("Migration Urgency Score",
                          f"{model.migration_urgency_score():.2f} / 1.00",
                          help="Composite Mosca-based urgency (1.0 = maximum urgency)")

            st.plotly_chart(_bitcoin_exposure_timeline(), use_container_width=True)

        # ------------------------------------------------------------------
        # Ethereum
        # ------------------------------------------------------------------
        with eth_tab:
            st.subheader("Ethereum PQC Gas Schedule")
            st.markdown(
                "ECDSA verification via `ecRecover` costs **3,000 gas**. A PQC precompile "
                "(as proposed in EIP-7696 drafts) would cost dramatically more — "
                "SLH-DSA-128s is **300× more expensive** to verify."
            )

            st.dataframe(
                _ethereum_gas_table(),
                use_container_width=True,
                hide_index=True,
            )

            col1, col2 = st.columns([3, 2])
            with col1:
                st.plotly_chart(_ethereum_gas_bar(), use_container_width=True)
            with col2:
                st.markdown("### Hybrid Period Overhead")
                st.caption(
                    "During migration, transactions carry BOTH classical and PQC signatures."
                )
                model = EthereumTxModel()
                for pqc_algo in ["ML-DSA-65", "Falcon-512", "SLH-DSA-128f"]:
                    ecdsa_sig = SIGNATURE_SIZES["ECDSA"]
                    ecdsa_pk  = PUBLIC_KEY_SIZES["ECDSA"]
                    pqc_sig   = SIGNATURE_SIZES.get(pqc_algo, 2_000)
                    pqc_pk    = PUBLIC_KEY_SIZES.get(pqc_algo, 1_000)
                    dual_gas  = model.dual_sig_gas(
                        "ECDSA", pqc_algo,
                        ecdsa_sig, ecdsa_pk,
                        pqc_sig, pqc_pk,
                    )
                    ecdsa_gas = model.tx_gas(ecdsa_sig, ecdsa_pk, sig_algorithm="ECDSA")
                    st.metric(
                        f"ECDSA + {pqc_algo}",
                        f"{dual_gas:,} gas",
                        delta=f"{dual_gas/ecdsa_gas:.0f}× vs ECDSA",
                        delta_color="inverse",
                    )

        # ------------------------------------------------------------------
        # Solana
        # ------------------------------------------------------------------
        with sol_tab:
            st.subheader("Solana Vote Transaction Overhead")
            st.markdown(
                "Vote transactions consume **~75% of block space** on Solana mainnet. "
                "Under PQC, votes become dramatically larger — potentially **saturating the "
                "entire block** before any user transactions can be included."
            )

            st.plotly_chart(_solana_vote_overhead_chart(), use_container_width=True)
            st.plotly_chart(_solana_cu_chart(), use_container_width=True)

            # Detailed table
            model = DEFAULT_SOLANA_TX_MODEL
            algos = [
                "Ed25519", "ML-DSA-44", "ML-DSA-65", "Falcon-512",
                "Falcon-1024", "SLH-DSA-128s", "SLH-DSA-128f",
            ]
            rows = []
            for algo in algos:
                cap = model.block_capacity_analysis(algo)
                rows.append({
                    "Algorithm":            algo,
                    "Vote Tx Size (B)":     f"{cap['vote_tx_size_bytes']:,}",
                    "Total Vote Bytes (MB)":f"{cap['vote_tx_bytes_total']/1e6:.2f}",
                    "User Capacity (MB)":   f"{cap['user_tx_capacity_bytes']/1e6:.2f}",
                    "Max User Txs":         f"{cap['max_user_txs']:,}",
                    "Vote Overhead":        f"{cap['vote_overhead_ratio']*100:.0f}%",
                    "Vote Saturated?":      "⛔ YES" if cap["is_vote_saturated"] else "✅ No",
                    "CU Saturated?":        "⛔ YES" if cap["is_cu_saturated"] else "✅ No",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
