"""Tab 5: QR Score -- composite quantum resistance readiness scoring per chain."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from blockchain.qr_score import (
    score_all_chains,
    SCORE_WEIGHTS, MIGRATION_FEASIBILITY, ZK_READINESS,
)
from app.components.charts import qr_radar_chart, qr_composite_bar_chart


def render(tab) -> None:
    """Render the QR Score tab."""
    with tab:
        st.header("Quantum Resistance Readiness Score")
        st.caption(
            "A composite scoring model that evaluates each blockchain's readiness "
            "for the post-quantum transition across five weighted dimensions."
        )

        # Educational context
        with st.expander("How the QR Score Works", expanded=True):
            st.markdown(
                "The QR Score evaluates quantum resistance readiness across "
                "**five dimensions**, each weighted by importance:\n\n"
                "| Dimension | Weight | What It Measures |\n"
                "|-----------|--------|------------------|\n"
                "| Throughput Retention | 30% | Best PQC algorithm's throughput vs baseline |\n"
                "| Signature Size | 20% | How much PQC signatures inflate vs classical |\n"
                "| Migration Feasibility | 25% | Practical difficulty of PQC adoption |\n"
                "| ZK Readiness | 15% | Chain's ability to leverage quantum-resistant ZK proofs |\n"
                "| Algorithm Diversity | 10% | Number of viable PQC algorithm families |\n\n"
                "Each dimension is scored 0-100, then weighted to produce a composite score "
                "and letter grade (A-F)."
            )

        st.divider()

        # Compute scores
        qr_scores = score_all_chains()

        # Grade cards
        st.subheader("Overall Grades")
        gc1, gc2, gc3 = st.columns(3)

        grade_colors = {
            "A": "green", "B": "green", "C": "orange", "D": "red", "F": "red",
        }

        for col, cs in zip([gc1, gc2, gc3], qr_scores):
            with col:
                grade_color = grade_colors.get(cs.grade, "gray")
                st.markdown(f"### {cs.chain}")
                st.markdown(f"## :{grade_color}[{cs.grade}]")
                st.metric(
                    "Composite Score",
                    f"{cs.composite_score:.1f} / 100",
                )
                st.caption(f"Best PQC: **{cs.best_pqc_algorithm}** ({cs.best_pqc_retention:.1%} retention)")

        st.divider()

        # Radar chart
        st.subheader("Dimension Comparison")
        st.plotly_chart(qr_radar_chart(qr_scores), use_container_width=True)

        # Composite bar chart
        st.plotly_chart(qr_composite_bar_chart(qr_scores), use_container_width=True)

        # Detailed dimension breakdown per chain
        st.divider()
        st.subheader("Detailed Dimension Breakdown")

        for cs in qr_scores:
            with st.expander(f"{cs.chain} -- {cs.composite_score:.1f}/100 (Grade: {cs.grade})", expanded=False):
                dim_rows = []
                for d in cs.dimensions:
                    dim_rows.append({
                        "Dimension": d.dimension.replace("_", " ").title(),
                        "Raw Score": f"{d.score:.1f}",
                        "Weight": f"{d.weight:.0%}",
                        "Weighted": f"{d.weighted_score:.1f}",
                        "Detail": d.detail,
                    })
                st.dataframe(pd.DataFrame(dim_rows), use_container_width=True, hide_index=True)

                st.markdown(f"**Recommendation:** {cs.recommendation}")

        # Migration feasibility details
        st.divider()
        st.subheader("Migration Feasibility Analysis")

        mf1, mf2, mf3 = st.columns(3)
        for col, chain_name in zip([mf1, mf2, mf3], ["Solana", "Bitcoin", "Ethereum"]):
            info = MIGRATION_FEASIBILITY[chain_name]
            with col:
                st.markdown(f"### {chain_name}")
                st.metric("Feasibility Score", f"{info['score']:.0f}/100")
                st.markdown(f"**Hard Fork Required:** {'Yes' if info['hard_fork_required'] else 'No'}")
                st.markdown(f"**Account Model:** {info['account_model']}")
                st.caption(info["rationale"])

        # ZK readiness details
        st.divider()
        st.subheader("ZK-STARK Readiness")

        zr1, zr2, zr3 = st.columns(3)
        for col, chain_name in zip([zr1, zr2, zr3], ["Solana", "Bitcoin", "Ethereum"]):
            info = ZK_READINESS[chain_name]
            with col:
                st.markdown(f"### {chain_name}")
                st.metric("ZK Readiness Score", f"{info['score']:.0f}/100")
                st.caption(info["rationale"])

        # Scoring weights explanation
        st.divider()
        with st.expander("Scoring Model Assumptions & Limitations"):
            st.markdown(
                "**Scoring Weights:**\n"
                + "\n".join(f"- {k.replace('_', ' ').title()}: {v:.0%}" for k, v in SCORE_WEIGHTS.items())
                + "\n\n"
                "**What this model captures:**\n"
                "- Throughput impact of the best PQC signature scheme per chain\n"
                "- Signature size inflation relative to classical schemes\n"
                "- Qualitative migration feasibility (governance, account model, timing)\n"
                "- ZK-STARK infrastructure readiness per chain\n"
                "- Diversity of viable PQC algorithm families (>10% throughput retention)\n\n"
                "**What this model does NOT capture:**\n"
                "- Ecosystem readiness (wallet support, tooling, developer adoption)\n"
                "- Governance velocity (how fast a chain can coordinate upgrades)\n"
                "- Economic incentives for migration\n"
                "- Specific timeline projections for quantum computer capabilities\n"
                "- Hybrid classical+PQC transition schemes\n\n"
                "**Note:** Migration feasibility and ZK readiness scores are "
                "qualitative assessments encoded as numeric values. They reflect "
                "expert judgment rather than empirical measurements."
            )

        # Download
        st.divider()
        qr_dl_rows = []
        for cs in qr_scores:
            for d in cs.dimensions:
                qr_dl_rows.append({
                    "Chain": cs.chain,
                    "Composite Score": cs.composite_score,
                    "Grade": cs.grade,
                    "Dimension": d.dimension,
                    "Raw Score": d.score,
                    "Weight": d.weight,
                    "Weighted Score": d.weighted_score,
                    "Detail": d.detail,
                    "Best PQC": cs.best_pqc_algorithm,
                    "Best PQC Retention": cs.best_pqc_retention,
                    "Recommendation": cs.recommendation,
                })
        st.download_button(
            "Download QR Scores CSV",
            pd.DataFrame(qr_dl_rows).to_csv(index=False),
            "qr_scores.csv",
            "text/csv",
            key="dl_qr",
        )
