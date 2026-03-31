"""Tab 5: Risk Dashboard — calibration, Nakamoto coefficient, migration timeline.

Shows:
  - Calibration status indicator (pass/fail per chain)
  - Migration timeline visualisation (congestion spike during dual-sig)
  - Counterintuitive findings from sensitivity analysis
"""

from __future__ import annotations

import math
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from simulator.calibration.baseline import CALIBRATION_TARGETS
from simulator.migration.dual_sig import (
    DualSigConfig,
    MigrationTimeline,
    bitcoin_ecdsa_to_falcon512,
    ethereum_ecdsa_to_mldsa65,
    solana_ed25519_to_falcon512,
)


# ---------------------------------------------------------------------------
# Calibration status (uses stored targets without running engine)
# ---------------------------------------------------------------------------

def _calibration_status_table() -> pd.DataFrame:
    """Build a calibration targets summary table (no engine run needed)."""
    rows = []
    chain_sources = {
        "bitcoin":  "https://mempool.space/graphs/mempool",
        "ethereum": "https://etherscan.io/charts",
        "solana":   "https://solanabeach.io / https://validators.app",
    }
    for chain, metrics in CALIBRATION_TARGETS.items():
        for metric, (target, tol) in metrics.items():
            rows.append({
                "Chain":     chain.title(),
                "Metric":    metric,
                "Target":    f"{target:.3g}",
                "Tolerance": f"±{tol*100:.0f}%",
                "Source":    chain_sources.get(chain, ""),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Migration timeline
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _migration_overhead_curve(
    classical_algo: str,
    pqc_algo: str,
    migration_blocks: int = 50_000,
    chain: str = "bitcoin",
) -> pd.DataFrame:
    """Compute effective sig+pk overhead ratio across migration phases."""
    cfg = DualSigConfig(
        classical_algo       = classical_algo,
        pqc_algo             = pqc_algo,
        adoption_curve       = "logistic",
        migration_start_block= 0,
        migration_end_block  = migration_blocks,
    )
    timeline = MigrationTimeline(
        dual_sig_config      = cfg,
        pre_migration_blocks = migration_blocks // 5,
        post_migration_blocks= migration_blocks // 5,
        phase_resolution     = 50,
    )

    rows = []
    for phase_cfg in timeline.sim_configs(base_chain=chain):
        rows.append({
            "Phase":           phase_cfg["phase_name"],
            "Block":           phase_cfg["start_block"],
            "PQC Fraction":    phase_cfg["pqc_fraction"],
            "Avg Sig+PK (B)": phase_cfg["avg_sig_bytes"] + phase_cfg["avg_pk_bytes"],
            "Overhead Ratio":  phase_cfg["overhead_ratio"],
            "Is Dual-Sig":     phase_cfg["is_dual_sig"],
        })

    return pd.DataFrame(rows)


def _migration_chart(df: pd.DataFrame, classical_algo: str, pqc_algo: str) -> go.Figure:
    """Plot the congestion spike during dual-sig migration."""
    fig = go.Figure()

    # Classical phase
    classical = df[df["Is Dual-Sig"] == False]
    fig.add_trace(go.Scatter(
        x=classical["Block"], y=classical["Overhead Ratio"],
        name="Classical / PQC-only",
        mode="lines",
        line=dict(color="#6c8ebf", width=2),
    ))

    # Dual-sig phase
    dual = df[df["Is Dual-Sig"] == True]
    fig.add_trace(go.Scatter(
        x=dual["Block"], y=dual["Overhead Ratio"],
        name="Dual-Sig (WORST CASE)",
        mode="lines",
        fill="tozeroy",
        line=dict(color="#FF3B3B", width=3),
        hovertemplate="Block %{x}<br>Overhead: %{y:.2f}×<extra>Dual-Sig Period</extra>",
    ))

    fig.add_hline(y=1.0, line_dash="dash", line_color="green",
                  annotation_text="Classical baseline")
    fig.update_layout(
        title   = (f"Migration Congestion Spike: {classical_algo} → {pqc_algo}<br>"
                   "<sup>Peak overhead = both signatures carried simultaneously</sup>"),
        xaxis   = dict(title="Block Height"),
        yaxis   = dict(title="Effective Tx Size Overhead Ratio (vs classical)"),
        legend  = dict(x=0.6, y=0.99),
        height  = 450,
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Counterintuitive findings
# ---------------------------------------------------------------------------

COUNTERINTUITIVE_FINDINGS = [
    {
        "title": "Bandwidth, not CPU, is the binding constraint",
        "detail": (
            "PQC signatures are 10–700× larger than classical ones. While verification "
            "time increases 5–100×, the dominant effect is block size bloat: larger blocks "
            "take longer to propagate, directly causing stale/orphan blocks. The compute "
            "bottleneck is secondary."
        ),
        "source": "Solana DES sweep (results/solana_sweep_enhanced.csv)",
        "icon": "🌐",
    },
    {
        "title": "The dual-sig period is worse than 100% PQC",
        "detail": (
            "During migration, transactions carry BOTH classical and PQC signatures. "
            "This is strictly worse than the post-migration state where only the PQC "
            "sig is needed. Network operators face a congestion spike peak before seeing "
            "any improvement — a classic J-curve."
        ),
        "source": "simulator/migration/dual_sig.py",
        "icon": "📉",
    },
    {
        "title": "Solana votes saturate before user transactions compete",
        "detail": (
            "Validator vote transactions consume ~75% of Solana's block space. Under "
            "ML-DSA-65, vote transactions alone exceed the 6 MB block limit. User "
            "transactions get zero capacity. The chain cannot process normal transactions "
            "at all — not because of fee pressure, but because the block is physically full."
        ),
        "source": "simulator/chains/solana_specific.py",
        "icon": "⛔",
    },
    {
        "title": "Falcon-512 outperforms NIST's recommended ML-DSA-65",
        "detail": (
            "ML-DSA-65 is NIST's primary recommendation (FIPS 204), but its 3.3 KB "
            "signatures are impractical for high-throughput chains. Falcon-512 (666 B "
            "signatures, pending FIPS as FN-DSA) retains 19–33% of baseline throughput "
            "versus 6% for ML-DSA-65 on Solana."
        ),
        "source": "results/summary_tables.md",
        "icon": "🦅",
    },
    {
        "title": "Ethereum gas limit headroom buys more time than block size",
        "detail": (
            "Ethereum's EIP-1559 fee mechanism + planned gas limit increases "
            "(30M → 180M) absorb PQC calldata overhead more gracefully than Bitcoin or "
            "Solana. The consensus layer (validator attestations at 800k+ validators) is "
            "the real Ethereum bottleneck — requiring 167+ Mbps per validator under "
            "ML-DSA without BLS aggregation."
        ),
        "source": "results/ethereum/consensus_layer.csv",
        "icon": "⚡",
    },
]


def render(tab):
    """Render the Risk Dashboard tab."""
    with tab:
        st.header("Risk Dashboard")
        st.caption(
            "Calibration status, migration timeline congestion modelling, "
            "and key counterintuitive findings from the simulation."
        )

        # ------------------------------------------------------------------
        # Calibration targets table
        # ------------------------------------------------------------------
        st.subheader("Calibration Targets")
        st.markdown(
            "The simulator must match these real-world metrics with classical "
            "signatures before PQC scenarios are trusted. A ≤20% relative error "
            "on propagation and stale rate is required."
        )
        st.dataframe(
            _calibration_status_table(),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Calibration is enforced in `simulator/calibration/baseline.py`. "
            "Run `python scripts/run_chain_analysis.py` to validate."
        )

        # ------------------------------------------------------------------
        # Migration timeline
        # ------------------------------------------------------------------
        st.subheader("Migration Congestion Spike")
        st.markdown(
            "The dual-signature period — where every transaction carries "
            "**both** classical and PQC signatures — is the worst-case phase "
            "for block space and fees."
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            chain_choice = st.selectbox(
                "Chain",
                ["bitcoin", "ethereum", "solana"],
                format_func=str.title,
                key="risk_chain",
            )
        with col2:
            pqc_choice = st.selectbox(
                "Target PQC Algorithm",
                ["Falcon-512", "ML-DSA-65", "ML-DSA-87", "SLH-DSA-128f"],
                key="risk_pqc",
            )

        classical_algo = {
            "bitcoin": "ECDSA",
            "ethereum": "ECDSA",
            "solana": "Ed25519",
        }.get(chain_choice, "ECDSA")

        migration_blocks = {
            "bitcoin":  52_560,
            "ethereum": 2_628_000,
            "solana":   78_840_000,
        }.get(chain_choice, 52_560)

        df = _migration_overhead_curve(
            classical_algo   = classical_algo,
            pqc_algo         = pqc_choice,
            migration_blocks = migration_blocks,
            chain            = chain_choice,
        )
        st.plotly_chart(_migration_chart(df, classical_algo, pqc_choice),
                        use_container_width=True)

        # Summary metrics
        summary = MigrationTimeline(
            dual_sig_config=DualSigConfig(
                classical_algo       = classical_algo,
                pqc_algo             = pqc_choice,
                adoption_curve       = "logistic",
                migration_start_block= 0,
                migration_end_block  = migration_blocks,
            )
        ).congestion_spike_summary()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Classical (sig+pk)", f"{summary['classical_sig_plus_pk_bytes']:,} B")
        c2.metric("Peak Dual-Sig",      f"{summary['dual_sig_plus_pk_bytes']:,} B",
                  delta=f"{summary['peak_overhead_ratio']:.1f}× overhead",
                  delta_color="inverse")
        c3.metric("Post-Migration",     f"{summary['pqc_only_sig_plus_pk_bytes']:,} B",
                  delta=f"{summary['pqc_overhead_ratio']:.1f}× vs classical",
                  delta_color="inverse")
        c4.metric("Peak Block",         f"{summary['peak_block_height']:,}")

        # ------------------------------------------------------------------
        # Counterintuitive findings
        # ------------------------------------------------------------------
        st.subheader("Key Counterintuitive Findings")
        st.caption(
            "These results are non-obvious and distinguish this work from "
            "a naive signature-swap analysis."
        )

        for finding in COUNTERINTUITIVE_FINDINGS:
            with st.expander(f"{finding['icon']} {finding['title']}"):
                st.markdown(finding["detail"])
                st.caption(f"Source: `{finding['source']}`")
