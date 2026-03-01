"""PQC Cross-Chain Simulator -- Streamlit Application.

Four tabs:
1. Overview -- Onboarding, vulnerability context, cross-chain comparison
2. Algorithms -- Side-by-side algorithm benchmarking
3. Block-Space -- Per-chain throughput impact analysis
4. PQC Shock -- Phase 2/3 Monte Carlo results

Each tab is implemented in a separate module under app/tabs/ to keep
individual files manageable. This file handles page config, sidebar, and
tab orchestration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work when run via
# `streamlit run app/pqc_demo_streamlit.py` from the repo root.
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
)

# ---------------------------------------------------------------------------
# Per-chain quantum vulnerability context (shared across tabs)
# ---------------------------------------------------------------------------
CHAIN_QUANTUM_CONTEXT = {
    "Solana": {
        "current_sig": "Ed25519",
        "quantum_threat": "HIGH",
        "threat_detail": (
            "Solana's Ed25519 signatures are vulnerable to quantum attack via "
            "Shor's algorithm. With ~400 ms slots, Solana has the tightest timing "
            "constraints of the three chains, making the PQC transition particularly "
            "challenging -- larger signatures directly reduce the high throughput "
            "that is Solana's primary value proposition."
        ),
        "migration_challenge": (
            "**Throughput-critical:** Solana processes ~4,000 TPS (theoretical) with "
            "Ed25519. PQC signatures are 10-500x larger, directly cutting throughput. "
            "Additionally, 70-80% of block space is consumed by validator vote "
            "transactions, which also need signature upgrades."
        ),
        "recommended_pqc": "Falcon-512",
        "recommendation_reason": (
            "Falcon-512 (666 B) offers the smallest PQC signatures, preserving "
            "~19% of baseline throughput (with 70% vote overhead). ML-DSA-65 "
            "(NIST recommended) retains ~6%. Without vote overhead, retention is higher."
        ),
    },
    "Bitcoin": {
        "current_sig": "ECDSA / Schnorr",
        "quantum_threat": "MODERATE",
        "threat_detail": (
            "Bitcoin's ECDSA (secp256k1) and Schnorr (BIP 340) signatures are "
            "vulnerable to Shor's algorithm. However, Bitcoin's 10-minute block "
            "time provides more room for larger signatures, and the SegWit witness "
            "discount (1/4 weight) partially offsets PQC size increases."
        ),
        "migration_challenge": (
            "**Consensus-critical:** Any signature scheme change requires a hard "
            "fork or new SegWit version. The UTXO model means all outputs with "
            "exposed public keys are vulnerable. Reused addresses (P2PKH with "
            "known pubkey) are at highest risk."
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
            "calldata size (16 gas/byte). The planned gas limit increases "
            "(30M → 60M (current) → 100M+ (roadmap target)) provide a natural buffer for absorbing "
            "larger PQC signatures."
        ),
        "migration_challenge": (
            "**Account-model advantage:** Unlike Bitcoin's UTXO model, Ethereum "
            "accounts can be migrated individually via account abstraction (EIP-4337). "
            "Smart contract wallets could adopt PQC signatures without a hard fork. "
            "However, EOA migration requires protocol-level changes."
        ),
        "recommended_pqc": "Falcon-512 or ML-DSA-44",
        "recommendation_reason": (
            "At the current gas limit, even ML-DSA-65 retains a useful fraction of "
            "ECDSA capacity. Falcon-512 retains more. Account abstraction wallets "
            "can adopt PQC independently of the base protocol."
        ),
    },
}

# ---------------------------------------------------------------------------
# Patch CHAIN_QUANTUM_CONTEXT with live-computed retention percentages
# ---------------------------------------------------------------------------
def _patch_retention_percentages():
    """Replace hardcoded retention claims with live computed values."""
    try:
        sol = compare_all_solana()
        btc = compare_all_bitcoin()
        eth = compare_all_ethereum()

        def _retention(comp, algo):
            for a in comp.analyses:
                if a.signature_type == algo:
                    return a.relative_to_baseline * 100
            return None

        sol_falcon = _retention(sol, "Falcon-512")
        sol_mldsa = _retention(sol, "ML-DSA-65")
        btc_falcon = _retention(btc, "Falcon-512")
        eth_falcon = _retention(eth, "Falcon-512")
        eth_mldsa = _retention(eth, "ML-DSA-65")

        if sol_falcon and sol_mldsa:
            CHAIN_QUANTUM_CONTEXT["Solana"]["recommendation_reason"] = (
                f"Falcon-512 (666 B) offers the smallest PQC signatures, "
                f"preserving ~{sol_falcon:.0f}% of baseline throughput. "
                f"ML-DSA-65 (NIST recommended) retains ~{sol_mldsa:.0f}%."
            )
        if btc_falcon:
            CHAIN_QUANTUM_CONTEXT["Bitcoin"]["recommendation_reason"] = (
                f"Falcon-512 benefits most from the SegWit discount and "
                f"retains ~{btc_falcon:.0f}% of baseline capacity."
            )
        if eth_falcon and eth_mldsa:
            CHAIN_QUANTUM_CONTEXT["Ethereum"]["recommendation_reason"] = (
                f"At the current gas limit, ML-DSA-65 retains "
                f"~{eth_mldsa:.0f}% of ECDSA capacity. "
                f"Falcon-512 retains ~{eth_falcon:.0f}%."
            )
    except Exception:
        pass  # Keep fallback hardcoded values if computation fails

_patch_retention_percentages()


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PQC Cross-Chain Simulator",
    page_icon="⛓️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar -- redesigned: navigation first, then reference material
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⛓️ PQC Chain Simulator")

    if MOCK_MODE:
        st.info(
            "**Demonstration mode** — liboqs not installed. "
            "Signature sizes and all blockchain calculations are NIST-accurate. "
            "Timing values are synthetic.",
            icon="ℹ️",
        )
    else:
        st.success("**Real mode** -- liboqs detected.", icon="✅")

    st.divider()

    # Navigation guidance -- now at the TOP of the sidebar
    st.caption("NAVIGATION")
    st.markdown(
        "1. **Overview** — Start here for context\n"
        "2. **Algorithms** — Benchmark PQC schemes\n"
        "3. **Block-Space** — Per-chain impact analysis\n"
        "4. **PQC Shock** — Monte Carlo simulation results"
    )

    st.divider()
    st.caption("QUICK REFERENCE")

    with st.expander("Algorithm Families"):
        st.markdown(
            "| Family | Type | Basis | Standard |\n"
            "|--------|------|-------|----------|\n"
            "| ML-KEM | KEM | Module lattices | FIPS 203 |\n"
            "| ML-DSA | Signature | Module lattices | FIPS 204 |\n"
            "| SLH-DSA | Signature | Hash-based | FIPS 205 |\n"
            "| Falcon | Signature | NTRU lattices | Pending (FN-DSA) |\n"
            "| Ed25519 | Signature | Elliptic curves | RFC 8032 |\n"
            "| ECDSA | Signature | Elliptic curves | FIPS 186 |"
        )

    with st.expander("NIST Security Levels"):
        st.markdown(
            "| Level | Equivalent | Example |\n"
            "|-------|------------|----------|\n"
            "| 1 | AES-128 | ML-KEM-512, SLH-DSA-128s, Falcon-512 |\n"
            "| 2 | SHA-256 | ML-DSA-44 |\n"
            "| 3 | AES-192 | ML-KEM-768, ML-DSA-65, SLH-DSA-192s |\n"
            "| 5 | AES-256 | ML-KEM-1024, ML-DSA-87, SLH-DSA-256f |"
        )

    with st.expander("What is Post-Quantum Cryptography?"):
        st.markdown(
            "Post-quantum cryptography (PQC) refers to algorithms designed to resist "
            "attacks from **quantum computers**. NIST standardized several PQC algorithms "
            "in 2024:\n\n"
            "- **FIPS 203 (ML-KEM)**: Key Encapsulation (lattice-based)\n"
            "- **FIPS 204 (ML-DSA)**: Digital Signatures (lattice-based)\n"
            "- **FIPS 205 (SLH-DSA)**: Digital Signatures (hash-based)\n"
            "- **Falcon**: Compact signatures (pending FIPS as FN-DSA)"
        )

    with st.expander("Why Blockchains Are Vulnerable"):
        st.markdown(
            "Every blockchain transaction requires a **digital signature** to prove "
            "ownership. These signatures use elliptic-curve cryptography (Ed25519, "
            "ECDSA, Schnorr) which is **broken by Shor's algorithm** on a sufficiently "
            "powerful quantum computer.\n\n"
            "**Key risk:** A quantum attacker could forge signatures to steal funds "
            "from any address whose public key has been revealed on-chain.\n\n"
            "The challenge: PQC signatures are **10x to 700x larger** than classical "
            "ones, directly reducing blockchain throughput."
        )

# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------
st.title("PQC Cross-Chain Simulator")
st.caption(
    "A cross-chain simulator quantifying how post-quantum cryptography signatures "
    "change security, decentralisation, and fees in real blockchain networks."
)

# ---------------------------------------------------------------------------
# TL;DR Executive Summary
# ---------------------------------------------------------------------------
st.markdown("---")
col_tldr1, col_tldr2, col_tldr3 = st.columns(3)
with col_tldr1:
    st.metric("The Problem", "10-700×", help="PQC signatures are 10-700× larger than classical ones")
    st.caption("PQC signatures are 10-700× larger than classical, directly reducing blockchain throughput")
with col_tldr2:
    st.metric("The Finding", "~89% PQC → Failure", help="At ~89% PQC adoption, Solana's stale rate exceeds 30%")
    st.caption("Block-size bloat (not computation) is the bottleneck — propagation delay causes stale blocks")
with col_tldr3:
    st.metric("The Solution", "Falcon-512", help="Smallest PQC signature retains most throughput")
    try:
        _sol_comp = compare_all_solana()
        _f512 = next((a for a in _sol_comp.analyses if a.signature_type == "Falcon-512"), None)
        _mldsa = next((a for a in _sol_comp.analyses if a.signature_type == "ML-DSA-65"), None)
        _tldr_text = (
            f"Falcon-512 (666 B) retains ~{_f512.relative_to_baseline*100:.0f}% throughput. "
            f"ML-DSA-65 (3.3 KB, NIST recommended) retains ~{_mldsa.relative_to_baseline*100:.0f}%"
            if _f512 and _mldsa else
            "Falcon-512 (666 B) offers the best throughput retention among PQC algorithms"
        )
    except Exception:
        _tldr_text = "Falcon-512 (666 B) offers the best throughput retention among PQC algorithms"
    col_tldr3.caption(_tldr_text)
st.markdown("---")

# ---------------------------------------------------------------------------
# Tab layout -- NEW order: Overview → Algorithms → Block-Space → PQC Shock
# ---------------------------------------------------------------------------
tab_overview, tab_compare, tab_block, tab_shock = st.tabs([
    "🧭 Overview",
    "⚖️ Algorithms",
    "📊 Block-Space",
    "💥 PQC Shock",
])

render_overview(tab_overview, CHAIN_QUANTUM_CONTEXT)
render_comparison(tab_compare)
render_block_space(tab_block, CHAIN_QUANTUM_CONTEXT)
render_pqc_shock(tab_shock)
