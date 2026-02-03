"""PQC Demo -- Streamlit Application.

Four tabs:
1. KEM Demo -- ML-KEM (FIPS 203) key encapsulation interactive walkthrough
2. Signature Demo -- ML-DSA / SLH-DSA / Falcon / Ed25519 / Hybrid signing
3. Block-Space Visualizer -- Solana, Bitcoin & Ethereum throughput impact analysis
4. Side-by-Side Comparison -- Compare multiple algorithms at once
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
import pandas as pd

from pqc_lib.mock import (
    MOCK_MODE, SIG_PARAMS, ED25519_PARAMS,
    FIPS_204_ALGOS, FIPS_205_ALGOS, FALCON_ALGOS,
)
from pqc_lib.kem import keygen as kem_keygen, encaps, decaps, KEM_ALGORITHMS
from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from benchmarks.bench import bench_kem, bench_sig
from blockchain.solana_model import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SIGNATURE_SIZES,
    SOLANA_BLOCK_SIZE_BYTES, SOLANA_BASE_TX_OVERHEAD,
    BITCOIN_BLOCK_WEIGHT_LIMIT, BITCOIN_BASE_TX_OVERHEAD,
    ETHEREUM_BLOCK_GAS_LIMIT, ETHEREUM_BASE_TX_OVERHEAD, ETHEREUM_BLOCK_TIME_MS,
    ETHEREUM_BASE_TX_GAS, ETHEREUM_CALLDATA_GAS_PER_BYTE,
)
from app.components.charts import (
    benchmark_bar_chart,
    block_space_chart,
    throughput_comparison_chart,
    signature_size_comparison,
    side_by_side_dual_axis_chart,
)

# ---------------------------------------------------------------------------
# Algorithm metadata for tooltips and educational context
# ---------------------------------------------------------------------------
ALGO_INFO = {
    "ML-KEM-512": ("FIPS 203 Level 1 (AES-128 equivalent)", "KEM", "Lattice (MLWE)"),
    "ML-KEM-768": ("FIPS 203 Level 3 (AES-192 equivalent)", "KEM", "Lattice (MLWE)"),
    "ML-KEM-1024": ("FIPS 203 Level 5 (AES-256 equivalent)", "KEM", "Lattice (MLWE)"),
    "Ed25519": ("Classical elliptic-curve signature (not PQC)", "Signature", "Elliptic Curve"),
    "ML-DSA-44": ("FIPS 204 Level 2", "Signature", "Lattice (MLWE)"),
    "ML-DSA-65": ("FIPS 204 Level 3 (recommended)", "Signature", "Lattice (MLWE)"),
    "ML-DSA-87": ("FIPS 204 Level 5", "Signature", "Lattice (MLWE)"),
    "SLH-DSA-128s": ("FIPS 205 Level 1 -- small/slow hash-based", "Signature", "Hash-based"),
    "SLH-DSA-128f": ("FIPS 205 Level 1 -- fast/large hash-based", "Signature", "Hash-based"),
    "SLH-DSA-192s": ("FIPS 205 Level 3 -- small/slow hash-based", "Signature", "Hash-based"),
    "SLH-DSA-256f": ("FIPS 205 Level 5 -- fast/large hash-based", "Signature", "Hash-based"),
    "Falcon-512": ("Level 1 -- pending FIPS as FN-DSA, compact sigs", "Signature", "Lattice (NTRU)"),
    "Falcon-1024": ("Level 5 -- pending FIPS as FN-DSA, compact sigs", "Signature", "Lattice (NTRU)"),
}


def _algo_help(algo: str) -> str:
    """Return a short help string for an algorithm."""
    info = ALGO_INFO.get(algo.replace("Hybrid-Ed25519+", ""))
    if algo.startswith("Hybrid-"):
        pqc = algo.replace("Hybrid-Ed25519+", "")
        return f"Hybrid: Ed25519 + {pqc} (dual classical+PQC security)"
    if info:
        return f"{info[0]} | {info[2]}-based"
    return ""


def _format_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1_000:
        return f"{n:,} B ({n / 1024:.1f} KB)"
    return f"{n:,} B"


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Post-Quantum Cryptography Demo",
    page_icon="🔐",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar -- global info and quick reference
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🔐 PQC Demo")

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
        "1. **KEM Demo** -- Key exchange walkthrough\n"
        "2. **Signatures** -- Sign & verify walkthrough\n"
        "3. **Block-Space** -- Solana, Bitcoin & Ethereum impact\n"
        "4. **Compare** -- Side-by-side algorithm comparison"
    )

# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------
st.title("Post-Quantum Cryptography Demo")
st.caption(
    "An interactive educational tool for exploring NIST post-quantum cryptography standards "
    "and their impact on blockchain systems."
)

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------
tab_kem, tab_sig, tab_block, tab_compare = st.tabs([
    "🔑 KEM Demo",
    "✍️ Signature Demo",
    "📊 Block-Space Visualizer",
    "⚖️ Side-by-Side Comparison",
])

# ===== TAB 1: KEM Demo ====================================================
with tab_kem:
    st.header("Key Encapsulation Mechanism (ML-KEM, FIPS 203)")

    with st.expander("What is a KEM?", expanded=False):
        st.markdown(
            "A **Key Encapsulation Mechanism (KEM)** allows two parties to establish "
            "a shared secret over an insecure channel. Unlike traditional key exchange "
            "(e.g., Diffie-Hellman), a KEM works in three steps:\n\n"
            "1. **Key Generation** -- Alice generates a public/secret keypair\n"
            "2. **Encapsulation** -- Bob uses Alice's public key to create a shared "
            "secret and a ciphertext\n"
            "3. **Decapsulation** -- Alice uses her secret key and the ciphertext to "
            "recover the same shared secret\n\n"
            "**ML-KEM** (FIPS 203) is a lattice-based KEM standardized by NIST. "
            "Its security relies on the hardness of the Module "
            "Learning With Errors (MLWE) problem."
        )

    col_algo, col_runs = st.columns([3, 1])
    with col_algo:
        kem_algo = st.selectbox(
            "Select KEM algorithm",
            KEM_ALGORITHMS,
            key="kem_algo",
            help="ML-KEM is the FIPS 203 standard. Available in three security levels: 512, 768, 1024.",
        )
    with col_runs:
        n_kem_runs = st.slider("Benchmark runs", 1, 20, 5, key="kem_runs",
                               help="Number of iterations for timing benchmarks")

    # Show algorithm info
    info = ALGO_INFO.get(kem_algo)
    if info:
        st.info(f"**{kem_algo}**: {info[0]} | {info[2]}-based", icon="ℹ️")

    st.markdown("---")
    st.markdown("##### Follow the steps below: Generate → Encapsulate → Decapsulate")

    # Track state for enabling/disabling steps
    has_kp = "kem_kp" in st.session_state
    has_enc = "kem_enc" in st.session_state

    col_kg, col_enc, col_dec = st.columns(3)

    # Step 1: Keygen
    with col_kg:
        st.markdown("**Step 1: Key Generation**")
        if st.button("Generate Keypair", key="kem_keygen", use_container_width=True,
                     type="primary" if not has_kp else "secondary"):
            kp = kem_keygen(kem_algo)
            st.session_state["kem_kp"] = kp
            st.session_state.pop("kem_enc", None)  # reset downstream
            has_kp = True

        if has_kp:
            kp = st.session_state["kem_kp"]
            c1, c2 = st.columns(2)
            c1.metric("Public Key", _format_bytes(len(kp.public_key)))
            c2.metric("Secret Key", _format_bytes(len(kp.secret_key)))
            st.metric("Keygen Time", f"{kp.keygen_time_ms:.3f} ms")
            with st.expander("View public key (hex)", expanded=False):
                st.code(kp.public_key[:64].hex(), language="text")
            st.success("Keypair ready. Proceed to Step 2.", icon="✅")
        else:
            st.caption("Click the button above to generate a keypair.")

    # Step 2: Encapsulation
    with col_enc:
        st.markdown("**Step 2: Encapsulate**")
        if st.button("Encapsulate", key="kem_encaps", use_container_width=True,
                     disabled=not has_kp,
                     type="primary" if has_kp and not has_enc else "secondary"):
            kp = st.session_state["kem_kp"]
            enc = encaps(kem_algo, kp.public_key)
            st.session_state["kem_enc"] = enc
            has_enc = True

        if not has_kp:
            st.caption("Complete Step 1 first.")
        elif has_enc:
            enc = st.session_state["kem_enc"]
            c1, c2 = st.columns(2)
            c1.metric("Ciphertext", _format_bytes(len(enc.ciphertext)))
            c2.metric("Shared Secret", f"{len(enc.shared_secret)} bytes")
            st.metric("Encaps Time", f"{enc.time_ms:.3f} ms")
            with st.expander("What happened?"):
                st.markdown(
                    f"Bob used Alice's **{len(st.session_state['kem_kp'].public_key):,}**-byte "
                    f"public key to produce a **{len(enc.ciphertext):,}**-byte ciphertext and "
                    f"a **{len(enc.shared_secret)}**-byte shared secret. The ciphertext is safe "
                    "to send over an insecure channel."
                )
            st.success("Ciphertext created. Proceed to Step 3.", icon="✅")
        else:
            st.caption("Click the button above to encapsulate.")

    # Step 3: Decapsulation
    with col_dec:
        st.markdown("**Step 3: Decapsulate**")
        if st.button("Decapsulate", key="kem_decaps", use_container_width=True,
                     disabled=not (has_kp and has_enc),
                     type="primary" if has_kp and has_enc else "secondary"):
            kp = st.session_state["kem_kp"]
            enc = st.session_state["kem_enc"]
            dec = decaps(kem_algo, kp.secret_key, enc.ciphertext)
            match = dec.shared_secret == enc.shared_secret
            st.metric("Shared Secret", f"{len(dec.shared_secret)} bytes")
            st.metric("Decaps Time", f"{dec.time_ms:.3f} ms")
            if match:
                st.success("Shared secrets **match** -- key exchange successful!", icon="✅")
            else:
                st.error("Shared secrets do NOT match.", icon="❌")
            with st.expander("What happened?"):
                st.markdown(
                    f"Alice used her **{len(kp.secret_key):,}**-byte secret key to decapsulate "
                    f"the **{len(enc.ciphertext):,}**-byte ciphertext and recovered the same "
                    f"**{len(dec.shared_secret)}**-byte shared secret. Both parties now share "
                    "an identical key for symmetric encryption."
                )

        if not (has_kp and has_enc):
            st.caption("Complete Steps 1 and 2 first.")

    # KEM Benchmark
    st.divider()
    st.subheader("KEM Benchmarks")
    st.caption("Runs keygen, encaps, and decaps for all KEM algorithms and reports average timing.")

    if st.button("Run KEM Benchmarks", key="run_kem_bench", type="primary"):
        with st.spinner("Benchmarking all KEM algorithms..."):
            all_kem_results = []
            progress = st.progress(0, text="Starting benchmarks...")
            for i, algo in enumerate(KEM_ALGORITHMS):
                progress.progress((i + 1) / len(KEM_ALGORITHMS),
                                  text=f"Benchmarking {algo}...")
                all_kem_results.extend(bench_kem(algo, n_kem_runs))
            progress.empty()
            df = pd.DataFrame([
                {
                    "algorithm": r.algorithm,
                    "operation": r.operation,
                    "mean_ms": round(r.mean_ms, 3),
                    "stddev_ms": round(r.stddev_ms, 3),
                    "peak_memory_kb": r.peak_memory_kb,
                }
                for r in all_kem_results
            ])
            st.session_state["kem_bench_df"] = df

    if "kem_bench_df" in st.session_state:
        df = st.session_state["kem_bench_df"]
        st.plotly_chart(benchmark_bar_chart(df, "KEM Benchmark Results"), use_container_width=True)
        with st.expander("View raw benchmark data"):
            st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            df.to_csv(index=False),
            "kem_benchmarks.csv",
            "text/csv",
            key="dl_kem_bench",
        )

# ===== TAB 2: Signature Demo ===============================================
with tab_sig:
    st.header("Digital Signatures")

    with st.expander("About PQC Digital Signatures", expanded=False):
        st.markdown(
            "Digital signatures prove that a message was created by the holder of a "
            "secret key, without revealing the key itself. PQC signatures replace "
            "classical algorithms (Ed25519, ECDSA) that are vulnerable to quantum attack.\n\n"
            "**ML-DSA** (FIPS 204): Lattice-based, larger signatures but "
            "very fast. Recommended by NIST for general use.\n\n"
            "**SLH-DSA** (FIPS 205): Hash-based, providing algorithmic diversity from "
            "lattice schemes. Very small public keys (32-64 B) but very large signatures "
            "(7.8 KB - 49.9 KB). Offers 's' (small) and 'f' (fast) parameter sets.\n\n"
            "**Falcon**: Lattice-based (NTRU), produces **much smaller signatures** "
            "(666 bytes vs 2,420 bytes at Level 1) but with more complex key generation. "
            "Pending FIPS standardization as FN-DSA.\n\n"
            "**Hybrid mode**: Concatenates Ed25519 + PQC signatures for dual "
            "classical/quantum security during the transition period. "
            "Note: this is a proof-of-concept concatenation without domain separation."
        )

    # Filter algorithms into categories for cleaner selection
    non_hybrid = [a for a in SIG_ALGORITHMS if not a.startswith("Hybrid")]
    hybrid = [a for a in SIG_ALGORITHMS if a.startswith("Hybrid")]

    col_algo, col_cat = st.columns([3, 1])
    with col_cat:
        show_hybrid = st.checkbox("Show hybrid algorithms", value=False,
                                  help="Hybrid = Ed25519 + PQC concatenated signatures")
    with col_algo:
        algo_choices = SIG_ALGORITHMS if show_hybrid else non_hybrid
        sig_algo = st.selectbox(
            "Select signature algorithm",
            algo_choices,
            key="sig_algo",
            help="Choose an algorithm to demonstrate keygen, sign, and verify.",
        )

    info = ALGO_INFO.get(sig_algo.replace("Hybrid-Ed25519+", ""))
    if sig_algo.startswith("Hybrid-"):
        pqc = sig_algo.replace("Hybrid-Ed25519+", "")
        st.info(f"**{sig_algo}**: Hybrid of Ed25519 + {pqc} (dual security)", icon="ℹ️")
    elif info:
        st.info(f"**{sig_algo}**: {info[0]} | {info[2]}-based", icon="ℹ️")

    col_msg, col_runs = st.columns([3, 1])
    with col_msg:
        message_input = st.text_input("Message to sign", value="Hello, post-quantum world!",
                                      help="The message that will be signed and verified")
    with col_runs:
        n_sig_runs = st.slider("Benchmark runs", 1, 20, 5, key="sig_runs")
    message = message_input.encode()

    st.markdown("---")
    st.markdown("##### Follow the steps: Generate Keys → Sign → Verify")

    has_sig_kp = "sig_kp" in st.session_state
    has_sig_result = "sig_result" in st.session_state

    col_skg, col_sgn, col_ver = st.columns(3)

    with col_skg:
        st.markdown("**Step 1: Key Generation**")
        if st.button("Generate Signing Keypair", key="sig_keygen", use_container_width=True,
                     type="primary" if not has_sig_kp else "secondary"):
            kp = sign_keygen(sig_algo)
            st.session_state["sig_kp"] = kp
            st.session_state.pop("sig_result", None)
            has_sig_kp = True

        if has_sig_kp:
            kp = st.session_state["sig_kp"]
            c1, c2 = st.columns(2)
            c1.metric("Public Key", _format_bytes(len(kp.public_key)))
            c2.metric("Secret Key", _format_bytes(len(kp.secret_key)))
            st.metric("Keygen Time", f"{kp.keygen_time_ms:.3f} ms")
            # Size comparison to Ed25519
            ed_pk = ED25519_PARAMS["public_key"]
            ratio = len(kp.public_key) / ed_pk
            if ratio > 1.5:
                st.caption(f"Public key is **{ratio:.0f}x larger** than Ed25519 ({ed_pk} B)")
            elif ratio < 1.0:
                st.caption(f"Public key is **smaller** than Ed25519 ({ed_pk} B)")
            st.success("Keypair ready. Proceed to Step 2.", icon="✅")
        else:
            st.caption("Click the button above to generate a keypair.")

    with col_sgn:
        st.markdown("**Step 2: Sign Message**")
        if st.button("Sign Message", key="sig_sign", use_container_width=True,
                     disabled=not has_sig_kp,
                     type="primary" if has_sig_kp and not has_sig_result else "secondary"):
            kp = st.session_state["sig_kp"]
            sr = sign(sig_algo, kp.secret_key, message, kp)
            st.session_state["sig_result"] = sr
            has_sig_result = True

        if not has_sig_kp:
            st.caption("Complete Step 1 first.")
        elif has_sig_result:
            sr = st.session_state["sig_result"]
            st.metric("Signature Size", _format_bytes(sr.signature_size))
            st.metric("Sign Time", f"{sr.time_ms:.3f} ms")
            ed_sig = ED25519_PARAMS["signature"]
            ratio = sr.signature_size / ed_sig
            if ratio > 1.5:
                st.metric("vs Ed25519", f"{ratio:.1f}x larger",
                          delta=f"+{sr.signature_size - ed_sig:,} bytes", delta_color="inverse")
            with st.expander("What happened?"):
                st.markdown(
                    f"The message \"{message_input}\" was signed with **{sig_algo}**, "
                    f"producing a **{sr.signature_size:,}**-byte signature. "
                    f"For comparison, Ed25519 produces a **{ed_sig}**-byte signature."
                )
            st.success("Signature ready. Proceed to Step 3.", icon="✅")
        else:
            st.caption("Click the button above to sign the message.")

    with col_ver:
        st.markdown("**Step 3: Verify Signature**")
        if st.button("Verify Signature", key="sig_verify", use_container_width=True,
                     disabled=not (has_sig_kp and has_sig_result),
                     type="primary" if has_sig_kp and has_sig_result else "secondary"):
            kp = st.session_state["sig_kp"]
            sr = st.session_state["sig_result"]
            vr = verify(sig_algo, kp.public_key, message, sr.signature, kp)
            st.metric("Verify Time", f"{vr.time_ms:.3f} ms")
            if vr.valid:
                st.success("Signature is **VALID** -- message authenticity confirmed!", icon="✅")
            else:
                st.error("Signature is **INVALID** -- message may have been tampered with.", icon="❌")
            with st.expander("What happened?"):
                st.markdown(
                    f"The verifier checked the **{sr.signature_size:,}**-byte signature against "
                    f"the **{len(kp.public_key):,}**-byte public key and the original message. "
                    f"{'The signature was valid, confirming the message was not tampered with.' if vr.valid else 'The signature did not match, indicating possible tampering.'}"
                )

        if not (has_sig_kp and has_sig_result):
            st.caption("Complete Steps 1 and 2 first.")

    # Signature Benchmark
    st.divider()
    st.subheader("Signature Benchmarks")
    st.caption("Runs keygen, sign, and verify for all signature algorithms and reports average timing.")

    if st.button("Run Signature Benchmarks", key="run_sig_bench", type="primary"):
        with st.spinner("Benchmarking all signature algorithms..."):
            all_sig_results = []
            bench_algos = SIG_ALGORITHMS if show_hybrid else non_hybrid
            progress = st.progress(0, text="Starting benchmarks...")
            for i, algo in enumerate(bench_algos):
                progress.progress((i + 1) / len(bench_algos),
                                  text=f"Benchmarking {algo}...")
                all_sig_results.extend(bench_sig(algo, n_sig_runs))
            progress.empty()
            df = pd.DataFrame([
                {
                    "algorithm": r.algorithm,
                    "operation": r.operation,
                    "mean_ms": round(r.mean_ms, 3),
                    "stddev_ms": round(r.stddev_ms, 3),
                    "peak_memory_kb": r.peak_memory_kb,
                }
                for r in all_sig_results
            ])
            st.session_state["sig_bench_df"] = df

    if "sig_bench_df" in st.session_state:
        df = st.session_state["sig_bench_df"]
        st.plotly_chart(benchmark_bar_chart(df, "Signature Benchmark Results"), use_container_width=True)
        with st.expander("View raw benchmark data"):
            st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            df.to_csv(index=False),
            "signature_benchmarks.csv",
            "text/csv",
            key="dl_sig_bench",
        )

# ===== TAB 3: Block-Space Visualizer =======================================
with tab_block:
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

    # Multi-signer control (shared across all chains)
    num_signers = st.slider(
        "Number of signers per transaction",
        min_value=1,
        max_value=5,
        value=1,
        key="num_signers",
        help="Multi-signature transactions multiply signature and public key sizes. "
             "E.g. a 3-signer ML-DSA-65 tx has ~10 KB of signatures alone.",
    )

    if chain == "Solana":
        with st.expander("About the Solana model"):
            st.markdown(
                "**Solana** uses Ed25519 signatures (64 bytes) with ~6 MB practical "
                "block size and 400 ms slot times.\n\n"
                "This model calculates how many transactions fit per block when "
                "the signature scheme changes. Larger PQC signatures mean fewer "
                "transactions per block and lower throughput.\n\n"
                "**Limitation:** Models signature contribution to transaction "
                "size only. Real transactions include additional program data. "
                "Also does not account for validator vote transactions (~50% of block space)."
            )

        # Presets
        st.markdown("##### Quick Presets")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            if st.button("Default Solana", key="sol_default", use_container_width=True,
                         help="6 MB block, 250 B overhead, 400 ms slot"):
                st.session_state["sol_block_size"] = SOLANA_BLOCK_SIZE_BYTES
                st.session_state["sol_base_overhead"] = SOLANA_BASE_TX_OVERHEAD
                st.session_state["sol_slot_time"] = 400
                st.rerun()
        with pc2:
            if st.button("High Throughput", key="sol_high", use_container_width=True,
                         help="12 MB block, 200 B overhead, 400 ms slot"):
                st.session_state["sol_block_size"] = 12_000_000
                st.session_state["sol_base_overhead"] = 200
                st.session_state["sol_slot_time"] = 400
                st.rerun()
        with pc3:
            if st.button("Constrained", key="sol_constrained", use_container_width=True,
                         help="3 MB block, 350 B overhead, 600 ms slot"):
                st.session_state["sol_block_size"] = 3_000_000
                st.session_state["sol_base_overhead"] = 350
                st.session_state["sol_slot_time"] = 600
                st.rerun()

        col_params, col_results = st.columns([1, 2])

        with col_params:
            st.markdown("##### Model Parameters")
            block_size = st.number_input(
                "Block size (bytes)",
                value=st.session_state.get("sol_block_size", SOLANA_BLOCK_SIZE_BYTES),
                min_value=100_000,
                max_value=50_000_000,
                step=1_000_000,
                key="sol_block_size",
                help="Solana practical block size (~6 MB default, theoretical max 32 MB)",
            )
            base_overhead = st.number_input(
                "Base tx overhead (bytes)",
                value=st.session_state.get("sol_base_overhead", SOLANA_BASE_TX_OVERHEAD),
                min_value=50,
                max_value=2000,
                step=10,
                key="sol_base_overhead",
                help="Transaction overhead excluding the signature (accounts, instructions, blockhash)",
            )
            slot_time = st.number_input(
                "Slot time (ms)",
                value=st.session_state.get("sol_slot_time", 400),
                min_value=100,
                max_value=2000,
                step=50,
                key="sol_slot_time",
                help="Target time per slot (400 ms default)",
            )

        comp = compare_all_solana(block_size, base_overhead, slot_time, num_signers=num_signers)

    elif chain == "Bitcoin":
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

        # Presets
        st.markdown("##### Quick Presets")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            if st.button("Default Bitcoin", key="btc_default", use_container_width=True,
                         help="4 MWU, 150 B overhead, 10 min blocks"):
                st.session_state["btc_block_weight"] = BITCOIN_BLOCK_WEIGHT_LIMIT
                st.session_state["btc_base_overhead"] = BITCOIN_BASE_TX_OVERHEAD
                st.session_state["btc_block_time"] = 600_000
                st.rerun()
        with pc2:
            if st.button("Larger Blocks", key="btc_large", use_container_width=True,
                         help="8 MWU, 150 B overhead, 10 min blocks"):
                st.session_state["btc_block_weight"] = 8_000_000
                st.session_state["btc_base_overhead"] = 150
                st.session_state["btc_block_time"] = 600_000
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
                min_value=100_000,
                max_value=16_000_000,
                step=1_000_000,
                key="btc_block_weight",
                help="BIP 141 weight limit (4,000,000 WU = 4 MWU default)",
            )
            btc_base_overhead = st.number_input(
                "Base tx overhead (bytes)",
                value=st.session_state.get("btc_base_overhead", BITCOIN_BASE_TX_OVERHEAD),
                min_value=50,
                max_value=1000,
                step=10,
                key="btc_base_overhead",
                help="Non-witness transaction overhead (version, locktime, I/O)",
            )
            block_time = st.number_input(
                "Block time (ms)",
                value=st.session_state.get("btc_block_time", 600_000),
                min_value=10_000,
                max_value=3_600_000,
                step=60_000,
                key="btc_block_time",
                help="Average time between blocks (600,000 ms = 10 min default)",
            )

        comp = compare_all_bitcoin(block_weight, btc_base_overhead, block_time, num_signers=num_signers)

    else:  # Ethereum
        with st.expander("About the Ethereum model"):
            st.markdown(
                "**Ethereum** uses ECDSA (secp256k1) signatures with a gas-based cost model.\n\n"
                "Unlike Solana and Bitcoin, Ethereum block capacity is measured in **gas** "
                "rather than bytes. Each transaction pays:\n"
                "- **21,000 gas** base intrinsic cost\n"
                "- **16 gas per non-zero byte** of calldata (signature + public key)\n\n"
                "The block gas limit is **30M gas** with **12-second** block times (post-Merge).\n\n"
                "PQC signatures increase calldata size, consuming more gas per transaction "
                "and reducing the number of transactions per block."
            )

        # Presets
        st.markdown("##### Quick Presets")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            if st.button("Default Ethereum", key="eth_default", use_container_width=True,
                         help="30M gas, 120 B overhead, 12s blocks"):
                st.session_state["eth_gas_limit"] = ETHEREUM_BLOCK_GAS_LIMIT
                st.session_state["eth_base_overhead"] = ETHEREUM_BASE_TX_OVERHEAD
                st.session_state["eth_block_time"] = ETHEREUM_BLOCK_TIME_MS
                st.rerun()
        with pc2:
            if st.button("Higher Gas Limit", key="eth_high", use_container_width=True,
                         help="60M gas, 120 B overhead, 12s blocks"):
                st.session_state["eth_gas_limit"] = 60_000_000
                st.session_state["eth_base_overhead"] = 120
                st.session_state["eth_block_time"] = 12_000
                st.rerun()
        with pc3:
            if st.button("Constrained Gas", key="eth_constrained", use_container_width=True,
                         help="15M gas, 120 B overhead, 12s blocks"):
                st.session_state["eth_gas_limit"] = 15_000_000
                st.session_state["eth_base_overhead"] = 120
                st.session_state["eth_block_time"] = 12_000
                st.rerun()

        col_params, col_results = st.columns([1, 2])

        with col_params:
            st.markdown("##### Model Parameters")
            eth_gas_limit = st.number_input(
                "Block gas limit",
                value=st.session_state.get("eth_gas_limit", ETHEREUM_BLOCK_GAS_LIMIT),
                min_value=1_000_000,
                max_value=100_000_000,
                step=5_000_000,
                key="eth_gas_limit",
                help="Ethereum block gas limit (30,000,000 default)",
            )
            eth_base_overhead = st.number_input(
                "Base tx overhead (bytes)",
                value=st.session_state.get("eth_base_overhead", ETHEREUM_BASE_TX_OVERHEAD),
                min_value=50,
                max_value=500,
                step=10,
                key="eth_base_overhead",
                help="Non-signature calldata overhead (to, value, nonce, etc.)",
            )
            eth_block_time = st.number_input(
                "Block time (ms)",
                value=st.session_state.get("eth_block_time", ETHEREUM_BLOCK_TIME_MS),
                min_value=1_000,
                max_value=60_000,
                step=1_000,
                key="eth_block_time",
                help="Slot time (12,000 ms = 12s default, post-Merge)",
            )

        comp = compare_all_ethereum(eth_gas_limit, eth_base_overhead, eth_block_time, num_signers=num_signers)

    # Results table
    with col_results:
        st.markdown("##### Results Summary")
        if num_signers > 1:
            st.caption(f"Modeling **{num_signers} signers** per transaction")
        summary_rows = []
        for a in comp.analyses:
            summary_rows.append({
                "Scheme": a.signature_type,
                "Sig Size (B)": f"{a.signature_bytes:,}",
                "Tx Size (B)": f"{a.tx_size_bytes:,}",
                "Txs/Block": f"{a.txs_per_block:,}",
                "TPS": f"{a.throughput_tps:,.1f}",
                "vs Baseline": f"{a.relative_to_baseline:.1%}",
                "Sig Overhead": f"{a.signature_overhead_pct:.1f}%",
            })
        summary_df = pd.DataFrame(summary_rows)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        # Download button for results
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
            f"{chain.lower()}_block_space_analysis.csv",
            "text/csv",
            key=f"dl_{chain.lower()}_results",
        )

    st.divider()

    # Charts
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
    falcon_size = SIGNATURE_SIZES.get("Falcon-512", 666)
    mldsa_size = SIGNATURE_SIZES.get("ML-DSA-44", 2420)
    falcon_ratio = mldsa_size // falcon_size

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
        st.caption(f"{best_pqc.throughput_tps:,.1f} TPS")
    with kf3:
        st.metric(
            f"Worst: {worst.signature_type}",
            f"{worst.txs_per_block:,} txs/block",
            delta=f"{worst.relative_to_baseline:.1%} of baseline",
            delta_color="inverse",
        )
        st.caption(f"{worst.throughput_tps:,.1f} TPS")

    st.info(
        f"Falcon-512 signatures (**{falcon_size} B**) are **{falcon_ratio}x smaller** "
        f"than ML-DSA-44 (**{mldsa_size:,} B**), making Falcon the most block-space "
        "efficient PQC signature scheme for blockchain applications.",
        icon="💡",
    )

# ===== TAB 4: Side-by-Side Comparison ======================================
with tab_compare:
    st.header("Side-by-Side Algorithm Comparison")

    with st.expander("How to use this tool", expanded=False):
        st.markdown(
            "1. Select **2 or more** signature algorithms to compare\n"
            "2. Optionally change the test message\n"
            "3. Click **Run Comparison** to see the results\n\n"
            "The comparison runs keygen, sign, and verify for each selected algorithm "
            "and displays the results side-by-side."
        )

    col_sel, col_msg = st.columns([3, 1])
    with col_sel:
        selected_algos = st.multiselect(
            "Select algorithms to compare (min 2)",
            SIG_ALGORITHMS,
            default=["Ed25519", "ML-DSA-65", "Falcon-512"],
            key="compare_algos",
            help="Pick algorithms to compare. Mix classical and PQC for the most insight.",
        )
    with col_msg:
        compare_msg = st.text_input(
            "Test message", value="comparison test", key="compare_msg"
        ).encode()

    enough_selected = len(selected_algos) >= 2

    if not enough_selected:
        st.warning("Please select at least 2 algorithms to compare.", icon="⚠️")

    if st.button("Run Comparison", key="run_compare", type="primary",
                 disabled=not enough_selected, use_container_width=False):
        with st.spinner("Running comparison..."):
            compare_results = {}
            progress = st.progress(0, text="Starting comparison...")
            for i, algo in enumerate(selected_algos):
                progress.progress((i + 1) / len(selected_algos),
                                  text=f"Testing {algo}...")
                kp = sign_keygen(algo)
                sr = sign(algo, kp.secret_key, compare_msg, kp)
                vr = verify(algo, kp.public_key, compare_msg, sr.signature, kp)
                compare_results[algo] = {"kp": kp, "sr": sr, "vr": vr}
            progress.empty()
            st.session_state["compare_results"] = compare_results

    if "compare_results" in st.session_state:
        results = st.session_state["compare_results"]

        # Metric cards for quick overview
        st.markdown("##### Quick Overview")
        metric_cols = st.columns(min(len(results), 4))
        for i, (algo, r) in enumerate(results.items()):
            with metric_cols[i % len(metric_cols)]:
                st.markdown(f"**{algo}**")
                st.metric("Signature", _format_bytes(r["sr"].signature_size))
                ratio = r["sr"].signature_size / ED25519_PARAMS["signature"]
                if ratio > 1.5:
                    st.caption(f"{ratio:.1f}x Ed25519")
                elif ratio == 1.0:
                    st.caption("(baseline)")

        st.markdown("---")

        # Detailed table
        st.markdown("##### Detailed Comparison")
        rows = []
        for algo, r in results.items():
            rows.append({
                "Algorithm": algo,
                "Public Key (B)": f"{len(r['kp'].public_key):,}",
                "Secret Key (B)": f"{len(r['kp'].secret_key):,}",
                "Signature (B)": f"{r['sr'].signature_size:,}",
                "vs Ed25519": f"{r['sr'].signature_size / 64:.1f}x",
                "Keygen (ms)": f"{r['kp'].keygen_time_ms:.3f}",
                "Sign (ms)": f"{r['sr'].time_ms:.3f}",
                "Verify (ms)": f"{r['vr'].time_ms:.3f}",
                "Valid": "Yes" if r["vr"].valid else "No",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Charts -- separate axes for size vs time
        st.markdown("##### Visual Comparison")
        sig_results = {algo: r["sr"] for algo, r in results.items()}
        st.plotly_chart(side_by_side_dual_axis_chart(sig_results), use_container_width=True)

        # Download
        dl_df = pd.DataFrame([
            {
                "Algorithm": algo,
                "Public Key Bytes": len(r["kp"].public_key),
                "Secret Key Bytes": len(r["kp"].secret_key),
                "Signature Bytes": r["sr"].signature_size,
                "Keygen ms": round(r["kp"].keygen_time_ms, 3),
                "Sign ms": round(r["sr"].time_ms, 3),
                "Verify ms": round(r["vr"].time_ms, 3),
                "Valid": r["vr"].valid,
            }
            for algo, r in results.items()
        ])
        st.download_button(
            "Download Comparison CSV",
            dl_df.to_csv(index=False),
            "algorithm_comparison.csv",
            "text/csv",
            key="dl_compare",
        )
