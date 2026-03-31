"""PQC Cross-Chain Simulator -- Streamlit Application (v2).

Five-tab dashboard architecture:

  Tab 1: Crypto Benchmarks   — real keygen/sign/verify measurements + hybrid period costs
  Tab 2: Chain Architecture  — Bitcoin UTXO vulnerability, Ethereum gas schedule, Solana vote overhead
  Tab 3: Network Simulator   — DES propagation, dual-sig migration phase slider
  Tab 4: Fee Market          — agent pool, censorship incentive, demand destruction
  Tab 5: Risk Dashboard      — calibration targets, migration congestion spike, key findings

Tabs 2, 4, and 5 are new additions to this research-v2 upgrade.
Tab 3 exposes the DualSigConfig controls introduced in simulator/migration/dual_sig.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when launched via:
#   streamlit run app/pqc_demo_streamlit.py
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import streamlit as st

from pqc_lib.mock import MOCK_MODE
from blockchain.chain_models import compare_all_solana, compare_all_bitcoin, compare_all_ethereum

from app.tabs import (
    render_overview,
    render_comparison,
    render_block_space,
    render_pqc_shock,
    render_chain_architecture,
    render_fee_economics,
    render_risk_dashboard,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title = "PQC Cross-Chain Simulator",
    page_icon  = "🔐",
    layout     = "wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🔐 PQC Simulator")
    st.markdown(
        "Cross-chain simulator quantifying the impact of post-quantum "
        "cryptography on blockchain throughput, fees, and security."
    )

    if MOCK_MODE:
        st.info(
            "**Mock Mode Active**\n\n"
            "Real PQC benchmarks are not available. "
            "Size and performance data are from NIST standards.",
            icon="ℹ️",
        )
    else:
        st.success("liboqs loaded — real PQC measurements active.", icon="✅")

    st.markdown("---")
    st.markdown("**Project:** UOSA_PQC — St Andrews Blockchain Society")
    st.markdown("**Branch:** `research-v2`")
    st.markdown("**Status:** Architecture-accurate, economically dynamic simulation")
    st.markdown("---")

    with st.expander("NIST PQC Standards"):
        st.markdown(
            "| Level | Classical | PQC Algorithms |\n"
            "|-------|-----------|----------------|\n"
            "| 1 | AES-128 | ML-KEM-512, ML-DSA-44, SLH-DSA-128 |\n"
            "| 3 | AES-192 | ML-KEM-768, ML-DSA-65, SLH-DSA-192 |\n"
            "| 5 | AES-256 | ML-KEM-1024, ML-DSA-87, SLH-DSA-256f |\n"
            "\nFalcon (FN-DSA) pending FIPS — compact sigs, fast verify."
        )

    with st.expander("What is PQC?"):
        st.markdown(
            "Post-quantum cryptography (PQC) algorithms resist quantum attacks.\n\n"
            "- **FIPS 203 (ML-KEM):** Key encapsulation (lattice)\n"
            "- **FIPS 204 (ML-DSA):** Signatures (lattice)\n"
            "- **FIPS 205 (SLH-DSA):** Signatures (hash-based)\n"
            "- **Falcon (FN-DSA):** Compact lattice signatures"
        )

    with st.expander("Why Blockchains Are at Risk"):
        st.markdown(
            "Every blockchain transaction uses elliptic-curve signatures "
            "(Ed25519, ECDSA, Schnorr) broken by Shor's algorithm on a CRQC.\n\n"
            "PQC signatures are **10–700× larger**, directly reducing throughput."
        )


# ---------------------------------------------------------------------------
# Main title & summary metrics
# ---------------------------------------------------------------------------
st.title("PQC Cross-Chain Simulator")
st.caption(
    "Architecture-accurate, economically dynamic cross-chain PQC impact simulator "
    "— Bitcoin · Ethereum · Solana"
)

st.markdown("---")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Signature Bloat", "10–700×",
              help="PQC signatures are 10–700× larger than classical ones")

with col2:
    # Dynamic threshold from sweep data
    _sweep_csv = Path(__file__).resolve().parent.parent / "results" / "pqc_sweep.csv"
    _threshold = "~37%"
    if _sweep_csv.exists():
        try:
            import pandas as _pd
            _df = _pd.read_csv(_sweep_csv)
            _df["pqc_pct"] = (_df["pqc_fraction"] * 100).round(1)
            _agg = _df.groupby("pqc_pct")["stale_rate"].mean().reset_index().sort_values("pqc_pct")
            for _i in range(len(_agg) - 1):
                if _agg.iloc[_i]["stale_rate"] < 0.30 <= _agg.iloc[_i + 1]["stale_rate"]:
                    _x1 = _agg.iloc[_i]["pqc_pct"]
                    _x2 = _agg.iloc[_i + 1]["pqc_pct"]
                    _y1 = _agg.iloc[_i]["stale_rate"]
                    _y2 = _agg.iloc[_i + 1]["stale_rate"]
                    _crossing = _x1 + (0.30 - _y1) * (_x2 - _x1) / (_y2 - _y1)
                    _threshold = f"~{_crossing:.0f}%"
                    break
        except Exception:
            pass
    st.metric("Solana Failure Threshold", _threshold,
              help="PQC adoption level where stale rate exceeds 30%")

with col3:
    st.metric("Best PQC for Throughput", "Falcon-512",
              help="Smallest PQC signatures: 666 B (vs 64 B Ed25519)")

with col4:
    st.metric("Critical Bottleneck", "Bandwidth",
              help="Block propagation (bandwidth), not CPU verification, is the binding constraint")

st.markdown("---")

# ---------------------------------------------------------------------------
# Tab layout — 5 tabs (Tab 1 includes Crypto Benchmarks + Hybrid Costs)
# ---------------------------------------------------------------------------

# Per-chain quantum vulnerability context passed to existing tabs
CHAIN_QUANTUM_CONTEXT = {
    "Solana": {
        "current_sig": "Ed25519",
        "quantum_threat": "HIGH",
        "threat_detail": (
            "Solana's Ed25519 signatures are vulnerable to quantum attack via "
            "Shor's algorithm. With ~400 ms slots, Solana has the tightest timing "
            "constraints of the three chains, making the PQC transition particularly "
            "challenging — larger signatures directly reduce the high throughput "
            "that is Solana's primary value proposition."
        ),
        "migration_challenge": (
            "**Throughput-critical:** Solana processes ~4,000 TPS (theoretical) with "
            "Ed25519. PQC signatures are 10–500× larger, directly cutting throughput. "
            "Additionally, 70–80% of block space is consumed by validator vote "
            "transactions, which also need signature upgrades."
        ),
        "recommended_pqc": "Falcon-512",
        "recommendation_reason": (
            "Falcon-512 (666 B) offers the smallest PQC signatures, preserving "
            "~19% of baseline throughput (with 70% vote overhead). ML-DSA-65 "
            "(NIST recommended) retains ~6%."
        ),
    },
    "Bitcoin": {
        "current_sig": "ECDSA / Schnorr",
        "quantum_threat": "MODERATE",
        "threat_detail": (
            "Bitcoin's ECDSA (secp256k1) and Schnorr (BIP 340) signatures are "
            "vulnerable to Shor's algorithm. The 10-minute block time provides "
            "more room for larger signatures, and the SegWit witness discount "
            "(1/4 weight) partially offsets PQC size increases."
        ),
        "migration_challenge": (
            "**Consensus-critical:** Any signature scheme change requires a hard "
            "fork or new SegWit version. The UTXO model means all outputs with "
            "exposed public keys are vulnerable. P2PK outputs (~1.7M BTC) are "
            "immediately at risk — no new transaction needed."
        ),
        "recommended_pqc": "Falcon-512",
        "recommendation_reason": (
            "Falcon-512 benefits most from the SegWit discount and retains ~33% "
            "of baseline capacity. Hybrid ECDSA+Falcon provides backward "
            "compatibility during a transition period."
        ),
    },
    "Ethereum": {
        "current_sig": "ECDSA (secp256k1)",
        "quantum_threat": "MODERATE-HIGH",
        "threat_detail": (
            "Ethereum's ECDSA signatures are vulnerable to Shor's algorithm. "
            "The gas-based cost model means PQC migration cost scales with "
            "calldata size (16 gas/byte). Planned gas limit increases provide a "
            "natural buffer for absorbing larger PQC signatures."
        ),
        "migration_challenge": (
            "**Account-model advantage:** Ethereum accounts can be migrated via "
            "account abstraction (EIP-4337). Smart contract wallets could adopt "
            "PQC without a hard fork. However, the consensus layer (800k+ validators) "
            "requires 167+ Mbps per validator under ML-DSA — the real bottleneck."
        ),
        "recommended_pqc": "Falcon-512",
        "recommendation_reason": (
            "Falcon-512 retains ~45% of block capacity. ML-DSA-65 retains ~17%. "
            "Account abstraction enables PQC wallets without a protocol hard fork."
        ),
    },
}

(
    tab_benchmarks,
    tab_architecture,
    tab_simulator,
    tab_fees,
    tab_risk,
) = st.tabs([
    "🔑 Crypto Benchmarks",
    "🏗️ Chain Architecture",
    "📡 Network Simulator",
    "💰 Fee Market",
    "⚠️ Risk Dashboard",
])

# Tab 1: Crypto Benchmarks (was Algorithms tab, extended with hybrid period costs)
render_comparison(tab_benchmarks)

# Tab 2: Chain Architecture (NEW)
render_chain_architecture(tab_architecture)

# Tab 3: Network Simulator (was Block-Space + PQC Shock, now merged with dual-sig controls)
# Render the block-space visualiser first, then the shock simulation
with tab_simulator:
    st.header("Network Simulator")
    st.caption(
        "Per-chain throughput impact analysis and Phase 2/3 Monte Carlo results."
    )
    net_tab1, net_tab2 = st.tabs(["Block Space", "PQC Shock Simulation"])
    render_block_space(net_tab1, CHAIN_QUANTUM_CONTEXT)
    render_pqc_shock(net_tab2)

# Tab 4: Fee Market & Economics (NEW)
render_fee_economics(tab_fees)

# Tab 5: Risk Dashboard (NEW)
render_risk_dashboard(tab_risk)
