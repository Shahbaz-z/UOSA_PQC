"""PQC Demo – Streamlit Application.

Four tabs:
1. KEM Demo – Kyber / ML-KEM key encapsulation interactive walkthrough
2. Signature Demo – Dilithium / ML-DSA / Falcon / Ed25519 / Hybrid signing
3. Block-Space Visualizer – Solana & Bitcoin throughput impact analysis
4. Side-by-Side Comparison – Compare multiple algorithms at once
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure project root is on sys.path so imports work when run via
# `streamlit run app/pqc_demo_streamlit.py` from the repo root.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import streamlit as st
import pandas as pd

from pqc_lib.mock import MOCK_MODE
from pqc_lib.kem import keygen as kem_keygen, encaps, decaps, KEM_ALGORITHMS
from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from benchmarks.bench import bench_kem, bench_sig, BenchmarkResult
from blockchain.solana_model import (
    compare_all_solana, compare_all_bitcoin,
    SIGNATURE_SIZES,
    SOLANA_BLOCK_SIZE_BYTES, SOLANA_BASE_TX_OVERHEAD,
    BITCOIN_BLOCK_WEIGHT_LIMIT, BITCOIN_BASE_TX_OVERHEAD,
)
from app.components.charts import (
    benchmark_bar_chart,
    block_space_chart,
    throughput_comparison_chart,
    signature_size_comparison,
    side_by_side_sig_chart,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Post-Quantum Cryptography Demo",
    page_icon="🔐",
    layout="wide",
)

st.title("Post-Quantum Cryptography Demo")
if MOCK_MODE:
    st.warning(
        "Running in **mock mode** (liboqs not available). "
        "Artifact sizes are accurate but timing data is synthetic.",
        icon="⚠️",
    )

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------
tab_kem, tab_sig, tab_block, tab_compare = st.tabs([
    "KEM Demo",
    "Signature Demo",
    "Block-Space Visualizer",
    "Side-by-Side Comparison",
])

# ===== TAB 1: KEM Demo ====================================================
with tab_kem:
    st.header("Key Encapsulation Mechanism (Kyber / ML-KEM)")
    st.markdown(
        "Kyber (FIPS 203: ML-KEM) is a lattice-based KEM selected by NIST for "
        "standardization. It allows two parties to establish a shared secret "
        "over an insecure channel."
    )

    kem_algo = st.selectbox("Select KEM algorithm", KEM_ALGORITHMS, key="kem_algo")
    n_kem_runs = st.slider("Benchmark runs", 1, 20, 5, key="kem_runs")

    col_kg, col_enc, col_dec = st.columns(3)

    # Keygen
    with col_kg:
        st.subheader("1. Key Generation")
        if st.button("Generate Keypair", key="kem_keygen"):
            kp = kem_keygen(kem_algo)
            st.session_state["kem_kp"] = kp
            st.metric("Public Key", f"{len(kp.public_key)} bytes")
            st.metric("Secret Key", f"{len(kp.secret_key)} bytes")
            st.metric("Time", f"{kp.keygen_time_ms:.3f} ms")
            st.code(kp.public_key[:32].hex() + "...", language="text")

    # Encapsulation
    with col_enc:
        st.subheader("2. Encapsulate")
        if st.button("Encapsulate", key="kem_encaps"):
            kp = st.session_state.get("kem_kp")
            if kp is None:
                st.error("Generate a keypair first.")
            else:
                enc = encaps(kem_algo, kp.public_key)
                st.session_state["kem_enc"] = enc
                st.metric("Ciphertext", f"{len(enc.ciphertext)} bytes")
                st.metric("Shared Secret", f"{len(enc.shared_secret)} bytes")
                st.metric("Time", f"{enc.time_ms:.3f} ms")
                st.code(enc.ciphertext[:32].hex() + "...", language="text")

    # Decapsulation
    with col_dec:
        st.subheader("3. Decapsulate")
        if st.button("Decapsulate", key="kem_decaps"):
            kp = st.session_state.get("kem_kp")
            enc = st.session_state.get("kem_enc")
            if kp is None or enc is None:
                st.error("Generate a keypair and encapsulate first.")
            else:
                dec = decaps(kem_algo, kp.secret_key, enc.ciphertext)
                st.metric("Shared Secret", f"{len(dec.shared_secret)} bytes")
                st.metric("Time", f"{dec.time_ms:.3f} ms")
                match = dec.shared_secret == enc.shared_secret
                if match:
                    st.success("Shared secrets match!")
                else:
                    st.error("Shared secrets do NOT match.")

    # KEM Benchmark
    st.divider()
    st.subheader("KEM Benchmarks")
    if st.button("Run KEM Benchmarks", key="run_kem_bench"):
        with st.spinner("Benchmarking..."):
            all_kem_results = []
            for algo in KEM_ALGORITHMS:
                all_kem_results.extend(bench_kem(algo, n_kem_runs))
            df = pd.DataFrame([
                {
                    "algorithm": r.algorithm,
                    "operation": r.operation,
                    "mean_ms": r.mean_ms,
                    "stddev_ms": r.stddev_ms,
                    "peak_memory_kb": r.peak_memory_kb,
                    "artifact_sizes": r.artifact_sizes,
                }
                for r in all_kem_results
            ])
            st.session_state["kem_bench_df"] = df

    if "kem_bench_df" in st.session_state:
        df = st.session_state["kem_bench_df"]
        st.plotly_chart(benchmark_bar_chart(df, "KEM Benchmark Results"), use_container_width=True)
        st.dataframe(df, use_container_width=True)

# ===== TAB 2: Signature Demo ===============================================
with tab_sig:
    st.header("Digital Signatures")
    st.markdown(
        "**Dilithium** (FIPS 204: ML-DSA) and **Falcon** are lattice-based signature "
        "schemes from the NIST PQC standards. Hybrid mode concatenates an Ed25519 "
        "signature with a PQC signature, providing security against both classical "
        "and quantum adversaries."
    )

    sig_algo = st.selectbox("Select signature algorithm", SIG_ALGORITHMS, key="sig_algo")
    message_input = st.text_input("Message to sign", value="Hello, post-quantum world!")
    message = message_input.encode()
    n_sig_runs = st.slider("Benchmark runs", 1, 20, 5, key="sig_runs")

    col_skg, col_sgn, col_ver = st.columns(3)

    with col_skg:
        st.subheader("1. Key Generation")
        if st.button("Generate Signing Keypair", key="sig_keygen"):
            kp = sign_keygen(sig_algo)
            st.session_state["sig_kp"] = kp
            st.metric("Public Key", f"{len(kp.public_key)} bytes")
            st.metric("Secret Key", f"{len(kp.secret_key)} bytes")
            st.metric("Time", f"{kp.keygen_time_ms:.3f} ms")

    with col_sgn:
        st.subheader("2. Sign")
        if st.button("Sign Message", key="sig_sign"):
            kp = st.session_state.get("sig_kp")
            if kp is None:
                st.error("Generate a keypair first.")
            else:
                sr = sign(sig_algo, kp.secret_key, message, kp)
                st.session_state["sig_result"] = sr
                st.metric("Signature Size", f"{sr.signature_size} bytes")
                st.metric("Time", f"{sr.time_ms:.3f} ms")
                # Compare to Ed25519
                ratio = sr.signature_size / 64
                st.metric("vs Ed25519", f"{ratio:.1f}x larger")

    with col_ver:
        st.subheader("3. Verify")
        if st.button("Verify Signature", key="sig_verify"):
            kp = st.session_state.get("sig_kp")
            sr = st.session_state.get("sig_result")
            if kp is None or sr is None:
                st.error("Generate keys and sign first.")
            else:
                vr = verify(sig_algo, kp.public_key, message, sr.signature, kp)
                st.metric("Time", f"{vr.time_ms:.3f} ms")
                if vr.valid:
                    st.success("Signature is VALID")
                else:
                    st.error("Signature is INVALID")

    # Signature Benchmark
    st.divider()
    st.subheader("Signature Benchmarks")
    if st.button("Run Signature Benchmarks", key="run_sig_bench"):
        with st.spinner("Benchmarking..."):
            all_sig_results = []
            for algo in SIG_ALGORITHMS:
                all_sig_results.extend(bench_sig(algo, n_sig_runs))
            df = pd.DataFrame([
                {
                    "algorithm": r.algorithm,
                    "operation": r.operation,
                    "mean_ms": r.mean_ms,
                    "stddev_ms": r.stddev_ms,
                    "peak_memory_kb": r.peak_memory_kb,
                    "artifact_sizes": r.artifact_sizes,
                }
                for r in all_sig_results
            ])
            st.session_state["sig_bench_df"] = df

    if "sig_bench_df" in st.session_state:
        df = st.session_state["sig_bench_df"]
        st.plotly_chart(benchmark_bar_chart(df, "Signature Benchmark Results"), use_container_width=True)
        st.dataframe(df, use_container_width=True)

# ===== TAB 3: Block-Space Visualizer =======================================
with tab_block:
    st.header("Block-Space Impact Analysis")

    chain = st.radio("Select blockchain", ["Solana", "Bitcoin"], horizontal=True, key="chain_select")

    if chain == "Solana":
        st.markdown(
            "Models how replacing Ed25519 signatures with PQC alternatives affects "
            "Solana transaction throughput."
            "\n\n**Limitations:** Models *signature contribution* to transaction "
            "size only. Real transactions include additional overhead."
        )

        col_params, col_results = st.columns([1, 2])

        with col_params:
            st.subheader("Model Parameters")
            block_size = st.number_input(
                "Block size (bytes)",
                value=SOLANA_BLOCK_SIZE_BYTES,
                min_value=100_000,
                max_value=50_000_000,
                step=1_000_000,
                key="sol_block_size",
            )
            base_overhead = st.number_input(
                "Base tx overhead (bytes, excl. signature)",
                value=SOLANA_BASE_TX_OVERHEAD,
                min_value=50,
                max_value=2000,
                step=10,
                key="sol_base_overhead",
            )
            slot_time = st.number_input(
                "Slot time (ms)",
                value=400,
                min_value=100,
                max_value=2000,
                step=50,
                key="sol_slot_time",
            )

        comp = compare_all_solana(block_size, base_overhead, slot_time)

    else:  # Bitcoin
        st.markdown(
            "Models how replacing ECDSA (secp256k1) signatures with PQC alternatives "
            "affects Bitcoin transaction throughput. "
            "\n\n**SegWit discount:** Witness data (signatures + pubkeys) counts at "
            "1/4 weight under BIP 141, partially offsetting PQC size increases."
        )

        col_params, col_results = st.columns([1, 2])

        with col_params:
            st.subheader("Model Parameters")
            block_weight = st.number_input(
                "Block weight limit (WU)",
                value=BITCOIN_BLOCK_WEIGHT_LIMIT,
                min_value=100_000,
                max_value=16_000_000,
                step=1_000_000,
                key="btc_block_weight",
            )
            btc_base_overhead = st.number_input(
                "Base tx overhead (bytes, excl. witness)",
                value=BITCOIN_BASE_TX_OVERHEAD,
                min_value=50,
                max_value=1000,
                step=10,
                key="btc_base_overhead",
            )
            block_time = st.number_input(
                "Block time (ms)",
                value=600_000,
                min_value=10_000,
                max_value=3_600_000,
                step=60_000,
                key="btc_block_time",
            )

        comp = compare_all_bitcoin(block_weight, btc_base_overhead, block_time)

    with col_results:
        st.subheader("Results Summary")
        summary_df = pd.DataFrame([
            {
                "Scheme": a.signature_type,
                "Sig Size (B)": a.signature_bytes,
                "Tx Size (B)": a.tx_size_bytes,
                "Txs/Block": a.txs_per_block,
                "TPS": a.throughput_tps,
                "vs Baseline": f"{a.relative_to_baseline:.1%}",
                "Sig Overhead %": f"{a.signature_overhead_pct:.1f}%",
            }
            for a in comp.analyses
        ])
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

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
    st.markdown(f"""
- **{baseline.signature_type} baseline**: {baseline.txs_per_block:,} txs/block ({baseline.throughput_tps:,.1f} TPS)
- **Best PQC ({best_pqc.signature_type})**: {best_pqc.txs_per_block:,} txs/block — **{best_pqc.relative_to_baseline:.1%}** of baseline
- **Worst case ({worst.signature_type})**: {worst.txs_per_block:,} txs/block — **{worst.relative_to_baseline:.1%}** of baseline
- Falcon-512 signatures ({SIGNATURE_SIZES.get('Falcon-512', 666)}B) are **{SIGNATURE_SIZES.get('Dilithium2', 2420) // SIGNATURE_SIZES.get('Falcon-512', 666)}x smaller** than Dilithium2 ({SIGNATURE_SIZES.get('Dilithium2', 2420)}B)
""")

# ===== TAB 4: Side-by-Side Comparison ======================================
with tab_compare:
    st.header("Side-by-Side Algorithm Comparison")
    st.markdown(
        "Select multiple algorithms to compare signature sizes, signing times, "
        "and verification times in a single view."
    )

    selected_algos = st.multiselect(
        "Select algorithms to compare",
        SIG_ALGORITHMS,
        default=["Ed25519", "Dilithium3", "Falcon-512"],
        key="compare_algos",
    )

    compare_msg = st.text_input(
        "Message to sign", value="comparison test", key="compare_msg"
    ).encode()

    if st.button("Run Comparison", key="run_compare") and len(selected_algos) >= 2:
        with st.spinner("Running comparison..."):
            compare_results = {}
            for algo in selected_algos:
                kp = sign_keygen(algo)
                sr = sign(algo, kp.secret_key, compare_msg, kp)
                vr = verify(algo, kp.public_key, compare_msg, sr.signature, kp)
                compare_results[algo] = {
                    "kp": kp,
                    "sr": sr,
                    "vr": vr,
                }
            st.session_state["compare_results"] = compare_results

    if "compare_results" in st.session_state:
        results = st.session_state["compare_results"]

        # Summary table
        rows = []
        for algo, r in results.items():
            rows.append({
                "Algorithm": algo,
                "Public Key (B)": len(r["kp"].public_key),
                "Secret Key (B)": len(r["kp"].secret_key),
                "Signature (B)": r["sr"].signature_size,
                "vs Ed25519": f"{r['sr'].signature_size / 64:.1f}x",
                "Keygen (ms)": f"{r['kp'].keygen_time_ms:.3f}",
                "Sign (ms)": f"{r['sr'].time_ms:.3f}",
                "Verify (ms)": f"{r['vr'].time_ms:.3f}",
                "Valid": r["vr"].valid,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Chart
        sig_results = {algo: r["sr"] for algo, r in results.items()}
        st.plotly_chart(side_by_side_sig_chart(sig_results), use_container_width=True)
