"""PQC Cross-Chain Simulator -- Streamlit Application.

Three tabs:
1. Block-Space Visualizer -- Solana, Bitcoin & Ethereum throughput impact analysis
2. Side-by-Side Comparison -- Compare multiple signature algorithms at once
3. Cross-Chain Summary -- Compare PQC impact across all three blockchains

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

from app.tabs import (
    render_block_space,
    render_comparison,
    render_cross_chain,
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
            "~80% of baseline throughput. ML-DSA-65 (NIST recommended) retains "
            "~62% but provides a stronger security margin."
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
            "Falcon-512 benefits most from the SegWit discount and retains ~85% "
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
            "(30M to 180M by 2026) provide a natural buffer for absorbing "
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
            "At 180M gas limit (2026 target), even ML-DSA-65 retains ~55% of "
            "ECDSA capacity. Falcon-512 retains ~85%. Account abstraction wallets "
            "can adopt PQC independently of the base protocol."
        ),
    },
}

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PQC Cross-Chain Simulator",
    page_icon="⛓️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar -- global info and quick reference
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⛓️ PQC Chain Simulator")

    if MOCK_MODE:
        st.warning(
            "**Mock mode** -- liboqs not available. "
            "Artifact sizes are NIST-accurate; timing is synthetic. "
            "Cryptographic security properties (verification, key agreement) "
            "are **simulated only** and not real.",
            icon="⚠️",
        )
    else:
        st.success("**Real mode** -- liboqs detected.", icon="✅")

    st.divider()
    st.caption("QUICK REFERENCE")

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

    st.divider()
    st.caption("NAVIGATION")
    st.markdown(
        "1. **Block-Space** -- Per-chain impact analysis\n"
        "2. **Compare** -- Side-by-side algorithm comparison\n"
        "3. **Cross-Chain** -- Summary across all blockchains\n"
        "4. **PQC Shock** -- Phase 2/3 Monte Carlo results"
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
# Tab layout -- rendering delegated to app.tabs modules
# ---------------------------------------------------------------------------
tab_block, tab_compare, tab_crosschain, tab_shock = st.tabs([
    "📊 Block-Space Visualizer",
    "⚖️ Side-by-Side Comparison",
    "🌐 Cross-Chain Summary",
    "💥 PQC Shock Simulator",
])

render_block_space(tab_block, CHAIN_QUANTUM_CONTEXT)
render_comparison(tab_compare)
render_cross_chain(tab_crosschain, CHAIN_QUANTUM_CONTEXT)
render_pqc_shock(tab_shock)
