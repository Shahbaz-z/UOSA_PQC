"""Tab 2: Side-by-Side Comparison -- compare multiple signature algorithms."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from pqc_lib.mock import ED25519_PARAMS
from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from app.components.charts import signature_size_bar_chart, performance_grouped_bar_chart
from app.utils import format_bytes, throughput_impact_category
ALGO_INFO = {
    "ML-KEM-512": ("FIPS 203 Level 1 (AES-128 equivalent)", "KEM", "Lattice (MLWE)"),
    "ML-KEM-768": ("FIPS 203 Level 3 (AES-192 equivalent)", "KEM", "Lattice (MLWE)"),
    "ML-KEM-1024": ("FIPS 203 Level 5 (AES-256 equivalent)", "KEM", "Lattice (MLWE)"),
    "Ed25519": ("Classical elliptic-curve signature (not PQC)", "Signature", "Elliptic Curve"),
    "ECDSA": ("Classical secp256k1 (Bitcoin/Ethereum, not PQC)", "Signature", "Elliptic Curve"),
    "Schnorr": ("BIP 340 Taproot (Bitcoin, not PQC)", "Signature", "Elliptic Curve"),
    "ML-DSA-44": ("FIPS 204 Level 2", "Signature", "Lattice (MLWE)"),
    "ML-DSA-65": ("FIPS 204 Level 3 (recommended)", "Signature", "Lattice (MLWE)"),
    "ML-DSA-87": ("FIPS 204 Level 5", "Signature", "Lattice (MLWE)"),
    "SLH-DSA-128s": ("FIPS 205 Level 1 -- small/slow hash-based", "Signature", "Hash-based"),
    "SLH-DSA-128f": ("FIPS 205 Level 1 -- fast/large hash-based", "Signature", "Hash-based"),
    "SLH-DSA-192s": ("FIPS 205 Level 3 -- small/slow hash-based", "Signature", "Hash-based"),
    "SLH-DSA-192f": ("FIPS 205 Level 3 -- fast/large hash-based", "Signature", "Hash-based"),
    "SLH-DSA-256s": ("FIPS 205 Level 5 -- small/slow hash-based", "Signature", "Hash-based"),
    "SLH-DSA-256f": ("FIPS 205 Level 5 -- fast/large hash-based", "Signature", "Hash-based"),
    "Falcon-512": ("Level 1 -- pending FIPS as FN-DSA, compact sigs", "Signature", "Lattice (NTRU)"),
    "Falcon-1024": ("Level 5 -- pending FIPS as FN-DSA, compact sigs", "Signature", "Lattice (NTRU)"),
}


def render(tab) -> None:
    """Render the Side-by-Side Comparison tab."""
    with tab:
        st.header("Side-by-Side Algorithm Comparison")

        with st.expander("How to use this tool", expanded=True):
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
            st.subheader("Quick Overview")
            metric_cols = st.columns(min(len(results), 4))
            for i, (algo, r) in enumerate(results.items()):
                with metric_cols[i % len(metric_cols)]:
                    st.markdown(f"**{algo}**")
                    algo_info = ALGO_INFO.get(algo.replace("Hybrid-Ed25519+", ""))
                    if algo_info:
                        st.caption(algo_info[2])
                    st.metric("Signature", format_bytes(r["sr"].signature_size))
                    ratio = r["sr"].signature_size / ED25519_PARAMS["signature"]
                    if ratio > 1.5:
                        st.caption(f"{ratio:.1f}x Ed25519 | {throughput_impact_category(1 / ratio)}")
                    elif ratio == 1.0:
                        st.caption("(baseline)")

            st.divider()

            # Detailed table
            st.subheader("Detailed Comparison")
            rows = []
            for algo, r in results.items():
                rows.append({
                    "Algorithm": algo,
                    "Family": ALGO_INFO.get(algo.replace("Hybrid-Ed25519+", ""), ("", "", "Unknown"))[2],
                    "Public Key (B)": f"{len(r['kp'].public_key):,}",
                    "Secret Key (B)": f"{len(r['kp'].secret_key):,}",
                    "Signature (B)": f"{r['sr'].signature_size:,}",
                    "vs Ed25519": f"{r['sr'].signature_size / ED25519_PARAMS['signature']:.1f}x",
                    "Keygen (ms)": f"{r['kp'].keygen_time_ms:.3f}",
                    "Sign (ms)": f"{r['sr'].time_ms:.3f}",
                    "Verify (ms)": f"{r['vr'].time_ms:.3f}",
                    "Valid": "Yes" if r["vr"].valid else "No",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Charts
            st.subheader("Visual Comparison")
            sig_results = {algo: r["sr"] for algo, r in results.items()}
            chart_c1, chart_c2 = st.columns(2)
            with chart_c1:
                st.plotly_chart(signature_size_bar_chart(sig_results), use_container_width=True)
            with chart_c2:
                st.plotly_chart(performance_grouped_bar_chart(results), use_container_width=True)

            # Download
            dl_df = pd.DataFrame([
                {
                    "Algorithm": algo,
                    "Family": ALGO_INFO.get(algo.replace("Hybrid-Ed25519+", ""), ("", "", "Unknown"))[2],
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
