"""Tab 4: ZK Proof Analysis -- zero-knowledge proof systems and quantum resistance."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from blockchain.zk_models import (
    ZK_PROOF_SYSTEMS,
    compare_all_zk_proofs, build_zk_vs_signatures_table,
    ETH_BLOCK_TIME_MS_DEFAULT,
    ECDSA_TX_GAS,
)
from app.components.charts import (
    zk_proof_size_vs_gas_chart,
    zk_throughput_comparison_chart,
    zk_vs_signatures_chart,
    zk_gas_breakdown_chart,
)


def render(tab) -> None:
    """Render the ZK Proof Analysis tab."""
    with tab:
        st.header("Zero-Knowledge Proof Analysis")
        st.caption(
            "Compare ZK-STARK and ZK-SNARK proof systems for blockchain quantum "
            "resistance. ZK-STARKs are quantum-resistant; most ZK-SNARKs are not."
        )

        # Educational context
        with st.expander("What are ZK-STARKs and ZK-SNARKs?", expanded=True):
            zk_ed1, zk_ed2 = st.columns(2)
            with zk_ed1:
                st.markdown(
                    "### ZK-STARKs (Quantum Resistant)\n"
                    "**S**calable **T**ransparent **AR**gument of **K**nowledge\n\n"
                    "- **Hash-based** -- no elliptic curves, resistant to Shor's algorithm\n"
                    "- **Transparent** -- no trusted setup ceremony required\n"
                    "- **Scalable** -- prover time scales quasi-linearly\n"
                    "- **Trade-off:** Larger proof sizes (45-200 KB)\n"
                    "- **Used by:** StarkNet, StarkEx, zkSync (partial)\n\n"
                    "STARKs are the only ZK proof system that is **inherently "
                    "quantum-resistant**, making them critical for post-quantum "
                    "blockchain infrastructure."
                )
            with zk_ed2:
                st.markdown(
                    "### ZK-SNARKs (NOT Quantum Resistant)\n"
                    "**S**uccinct **N**on-interactive **AR**gument of **K**nowledge\n\n"
                    "- **Pairing-based** -- relies on elliptic curves (vulnerable to Shor's)\n"
                    "- **Compact** -- very small proofs (128-600 bytes)\n"
                    "- **Trusted setup** -- Groth16 requires per-circuit ceremony\n"
                    "- **Trade-off:** Smaller proofs but NOT quantum-resistant\n"
                    "- **Used by:** Zcash, Tornado Cash, zkSync Era, Polygon zkEVM\n\n"
                    "Most deployed ZK systems use SNARKs for their compactness, but "
                    "will need migration to STARKs or PQC-SNARKs for quantum resistance."
                )

        st.divider()

        # Gas limit configuration
        st.markdown("##### Ethereum Gas Limit")
        zk_gc1, zk_gc2 = st.columns([2, 1])
        with zk_gc1:
            zk_gas_limit = st.select_slider(
                "Gas limit for analysis",
                options=[30_000_000, 36_000_000, 60_000_000, 80_000_000, 180_000_000],
                value=30_000_000,
                format_func=lambda x: f"{x // 1_000_000}M",
                key="zk_gas_limit",
                help="Select the Ethereum gas limit to model. Higher limits accommodate larger ZK proofs more easily.",
            )
        with zk_gc2:
            st.caption(
                f"Block gas: {zk_gas_limit:,}\n\n"
                f"ECDSA baseline: {zk_gas_limit // ECDSA_TX_GAS:,} txs/block"
            )

        st.divider()

        # Run analysis
        zk_analyses = compare_all_zk_proofs(
            block_gas_limit=zk_gas_limit,
            block_time_ms=ETH_BLOCK_TIME_MS_DEFAULT,
        )

        # Proof system overview table
        st.subheader("Proof System Comparison")
        zk_rows = []
        for a in zk_analyses:
            zk_rows.append({
                "System": a.proof_system,
                "Family": a.proof_family,
                "Proof Size": f"{a.proof_bytes:,} B",
                "Verification Gas": f"{a.verification_gas:,}",
                "Total Tx Gas": f"{a.total_tx_gas:,}",
                "Txs/Block": f"{a.txs_per_block:,}",
                "TPS": f"{a.throughput_tps:,.2f}",
                "vs ECDSA": f"{a.relative_to_ecdsa:.1%}",
                "QR": "Yes" if a.quantum_resistant else "No",
                "Trusted Setup": "Yes" if a.trusted_setup else "No",
            })
        st.dataframe(pd.DataFrame(zk_rows), use_container_width=True, hide_index=True)

        # Key metrics
        st.divider()
        best_qr = max(
            [a for a in zk_analyses if a.quantum_resistant],
            key=lambda a: a.txs_per_block,
        )
        best_compact = max(zk_analyses, key=lambda a: a.txs_per_block)
        worst = min(zk_analyses, key=lambda a: a.txs_per_block)

        zm1, zm2, zm3 = st.columns(3)
        with zm1:
            st.metric("Best Quantum-Resistant", f"{best_qr.proof_system}")
            st.caption(
                f"{best_qr.throughput_tps:,.2f} TPS | "
                f"{best_qr.relative_to_ecdsa:.1%} of ECDSA"
            )
        with zm2:
            st.metric("Most Compact (any)", f"{best_compact.proof_system}")
            st.caption(
                f"{best_compact.throughput_tps:,.2f} TPS | "
                f"{ZK_PROOF_SYSTEMS[best_compact.proof_system].proof_bytes:,} B proof"
            )
        with zm3:
            st.metric("Highest Gas Cost", f"{worst.proof_system}")
            st.caption(
                f"{worst.throughput_tps:,.2f} TPS | "
                f"{worst.verification_gas:,} gas verification"
            )

        # Charts
        st.divider()
        st.subheader("Visualizations")

        zk_ch1, zk_ch2 = st.columns(2)
        with zk_ch1:
            st.plotly_chart(zk_proof_size_vs_gas_chart(zk_analyses), use_container_width=True)
        with zk_ch2:
            st.plotly_chart(zk_throughput_comparison_chart(zk_analyses), use_container_width=True)

        st.plotly_chart(zk_gas_breakdown_chart(zk_analyses), use_container_width=True)

        # ZK vs Signatures comparison
        st.divider()
        st.subheader("ZK Proofs vs PQC Signatures (Ethereum)")
        st.caption(
            "Direct comparison of ZK proof systems against signature schemes "
            "on Ethereum's gas model. This shows how ZK proofs compare to both "
            "classical and PQC signatures in terms of throughput."
        )

        zk_vs_sig_rows = build_zk_vs_signatures_table(
            block_gas_limit=zk_gas_limit,
            block_time_ms=ETH_BLOCK_TIME_MS_DEFAULT,
        )
        st.dataframe(pd.DataFrame(zk_vs_sig_rows), use_container_width=True, hide_index=True)

        st.plotly_chart(zk_vs_signatures_chart(zk_vs_sig_rows), use_container_width=True)

        # Educational summary
        st.divider()
        st.subheader("Key Takeaways")

        st.info(
            "**ZK-STARKs are the only quantum-resistant ZK proof system.** "
            "Their larger proof sizes (45-200 KB) result in higher gas costs, "
            "but Ethereum's planned gas limit increases (30M to 180M) will "
            "progressively accommodate them. At 180M gas, STARK-S achieves "
            f"~{compare_all_zk_proofs(180_000_000)[3].throughput_tps:,.1f} TPS.",
            icon="💡",
        )

        st.warning(
            "**ZK-SNARKs (Groth16, PLONK, Halo2) are NOT quantum-resistant.** "
            "They rely on elliptic-curve pairings or polynomial commitments "
            "vulnerable to Shor's algorithm. Projects using SNARKs today will "
            "need to migrate to STARKs or PQC-enhanced SNARKs.",
            icon="⚠️",
        )

        # Model assumptions
        with st.expander("ZK Model Assumptions & Limitations"):
            st.markdown(
                "**What this model captures:**\n"
                "- Proof size contribution to calldata gas cost (16 gas/byte)\n"
                "- On-chain verification gas cost per proof system\n"
                "- Block throughput impact at various gas limits\n"
                "- Comparison against PQC signature schemes\n\n"
                "**What this model does NOT capture:**\n"
                "- Proof generation (proving) time and cost\n"
                "- Recursive proof composition (proof aggregation)\n"
                "- Batch verification amortization\n"
                "- L2 rollup economics (amortized proving across many transactions)\n"
                "- EIP-4844 blob-based data availability (reduces calldata costs)\n"
                "- Precompile gas cost changes (e.g., EIP-2537 BLS12-381)\n\n"
                "**Note on L2 context:** In practice, ZK rollups batch thousands "
                "of transactions into a single proof submitted on-chain. The "
                "per-transaction cost is therefore much lower than modeled here. "
                "This analysis shows the **single-proof-per-transaction** scenario "
                "to enable direct comparison with signature schemes."
            )

        # Download
        st.divider()
        zk_dl_rows = []
        for a in zk_analyses:
            zk_dl_rows.append({
                "System": a.proof_system,
                "Family": a.proof_family,
                "Proof Bytes": a.proof_bytes,
                "Verification Gas": a.verification_gas,
                "Total Tx Gas": a.total_tx_gas,
                "Txs Per Block": a.txs_per_block,
                "TPS": a.throughput_tps,
                "Relative to ECDSA": a.relative_to_ecdsa,
                "Quantum Resistant": a.quantum_resistant,
                "Trusted Setup": a.trusted_setup,
            })
        st.download_button(
            "Download ZK Analysis CSV",
            pd.DataFrame(zk_dl_rows).to_csv(index=False),
            "zk_proof_analysis.csv",
            "text/csv",
            key="dl_zk",
        )
