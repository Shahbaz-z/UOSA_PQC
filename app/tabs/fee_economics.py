"""Tab 4: Fee Market & Economics — agent behaviour, validator incentives.

Shows:
  - Agent pool composition slider (retail/whale/bot mix)
  - Fee premium by algorithm heatmap
  - Validator censorship incentive chart (fee multiplier needed)
  - Demand destruction curve (txs/block vs fee pressure)
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
from simulator.economics.user_agents import AgentPool, CHAIN_AGENT_MIX
from simulator.economics.block_builder import BlockBuilder
from simulator.chains.ethereum_specific import PQC_VERIFICATION_GAS


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

CHAIN_SCORING: dict = {
    "bitcoin":  "fee_per_weight_unit",
    "ethereum": "fee_per_gas",
    "solana":   "fee_per_compute_unit",
}

CHAIN_CLASSICAL: dict = {
    "bitcoin":  "ECDSA",
    "ethereum": "ECDSA",
    "solana":   "Ed25519",
}


@st.cache_data(show_spinner=False)
def _censorship_threshold_df(chain: str) -> pd.DataFrame:
    """Compute censorship thresholds for all algorithms on a chain."""
    builder = BlockBuilder(
        chain                = chain,
        sig_preference_model = CHAIN_SCORING.get(chain, "fee_per_gas"),
        classical_algo       = CHAIN_CLASSICAL.get(chain, "ECDSA"),
    )
    thresholds = builder.censorship_threshold(
        algorithms=[
            "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
            "Falcon-512", "Falcon-1024",
            "SLH-DSA-128s", "SLH-DSA-128f",
        ],
        baseline_fee=1.0,
    )
    rows = []
    for algo, mult in sorted(thresholds.items(), key=lambda x: x[1]):
        rows.append({
            "Algorithm":          algo,
            "Fee Premium Needed": f"{mult:.1f}×",
            "Premium Multiplier": mult,
        })
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _demand_curve(chain: str, sig_algo: str) -> list:
    """Compute the demand elasticity curve for a chain."""
    pool = AgentPool(chain=chain, pool_size=500, seed=42)
    return pool.fee_elasticity_curve(
        baseline_fee_rate = 1.0,
        max_multiplier    = 20.0,
        steps             = 40,
        sig_algorithm     = sig_algo,
    )


def _censorship_chart(chain: str) -> go.Figure:
    df = _censorship_threshold_df(chain)
    fig = go.Figure(go.Bar(
        x           = df["Algorithm"],
        y           = df["Premium Multiplier"],
        marker_color= [ALGO_COLORS.get(a, "#aaa") for a in df["Algorithm"]],
        text        = df["Fee Premium Needed"],
        textposition= "outside",
        hovertemplate="%{x}<br>Must pay %{text} vs classical<extra></extra>",
    ))
    fig.add_hline(
        y=1.0, line_dash="dash", line_color="green",
        annotation_text="Classical baseline (1×)",
    )
    fig.update_layout(
        title  = f"{chain.title()} — Fee Premium Required for Equal Validator Priority",
        yaxis  = dict(title="Fee Multiplier vs Classical", type="log"),
        xaxis  = dict(title="PQC Algorithm"),
        height = 400,
    )
    return fig


def _demand_destruction_chart(chain: str, sig_algo: str) -> go.Figure:
    curve = _demand_curve(chain, sig_algo)
    mults = [d["fee_multiplier"] for d in curve]
    subs  = [d["txs_submitted"]  for d in curve]
    abnd  = [d["txs_abandoned"]  for d in curve]
    l2mig = [d["l2_migrations"]  for d in curve]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=mults, y=subs,
        name="Submitted",
        fill="tozeroy",
        line=dict(color="#4caf50", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=mults, y=abnd,
        name="Abandoned",
        line=dict(color="#e53935", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=mults, y=l2mig,
        name="L2 Migrations",
        line=dict(color="#9945FF", dash="dash", width=2),
    ))
    fig.update_layout(
        title    = f"Demand Destruction: {chain.title()} under {sig_algo}",
        xaxis    = dict(title="Fee Multiplier vs Baseline"),
        yaxis    = dict(title="Agent Count"),
        hovermode= "x unified",
        height   = 400,
    )
    return fig


def _fee_heatmap(chains: list) -> go.Figure:
    """2D heatmap: algorithm × chain → fee premium multiplier."""
    algos = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "Falcon-512", "Falcon-1024",
             "SLH-DSA-128s", "SLH-DSA-128f"]

    z_matrix = []
    for chain in chains:
        builder = BlockBuilder(
            chain                = chain,
            sig_preference_model = CHAIN_SCORING.get(chain, "fee_per_gas"),
            classical_algo       = CHAIN_CLASSICAL.get(chain, "ECDSA"),
        )
        thresholds = builder.censorship_threshold(algorithms=algos, baseline_fee=1.0)
        row = []
        for algo in algos:
            val = thresholds.get(algo, float("inf"))
            row.append(min(val, 100.0))  # cap for display
        z_matrix.append(row)

    # Clamp inf for display
    import math
    z_clean = [[min(v, 100) if not math.isinf(v) else 100 for v in row] for row in z_matrix]

    fig = go.Figure(data=go.Heatmap(
        z             = z_clean,
        x             = algos,
        y             = [c.title() for c in chains],
        colorscale    = "RdYlGn_r",
        text          = [[f"{v:.1f}×" for v in row] for row in z_clean],
        texttemplate  = "%{text}",
        hovertemplate = "Chain: %{y}<br>Algo: %{x}<br>Fee Premium: %{z:.1f}×<extra></extra>",
    ))
    fig.update_layout(
        title  = "Validator Censorship Incentive: Fee Premium to Match Classical Priority",
        xaxis  = dict(title="PQC Algorithm"),
        yaxis  = dict(title="Chain"),
        height = 360,
    )
    return fig


def render(tab):
    """Render the Fee Market & Economics tab."""
    with tab:
        st.header("Fee Market & Economics")
        st.caption(
            "Rational validators prefer algorithms with lower verification cost per unit "
            "fee revenue. Under PQC, this creates systematic censorship incentives "
            "and demand destruction feedback loops."
        )

        # Chain selector
        chain = st.selectbox(
            "Select Chain",
            ["ethereum", "bitcoin", "solana"],
            format_func=str.title,
            key="econ_chain",
        )

        # ------------------------------------------------------------------
        # Censorship incentive
        # ------------------------------------------------------------------
        st.subheader("Validator Censorship Incentive")
        st.markdown(
            "A validator maximising fee/gas or fee/CU will **deprioritise** PQC transactions "
            "that cost more to verify. This heatmap shows the fee premium a PQC user must "
            "pay to achieve equal inclusion probability as a classical transaction."
        )

        col1, col2 = st.columns([2, 1])
        with col1:
            st.plotly_chart(_censorship_chart(chain), use_container_width=True)
        with col2:
            df = _censorship_threshold_df(chain)
            st.dataframe(
                df[["Algorithm", "Fee Premium Needed"]],
                use_container_width=True,
                hide_index=True,
            )

        st.plotly_chart(_fee_heatmap(["bitcoin", "ethereum", "solana"]),
                        use_container_width=True)

        # ------------------------------------------------------------------
        # Agent pool / demand destruction
        # ------------------------------------------------------------------
        st.subheader("Demand Destruction Curve")
        st.markdown(
            "As PQC inflates fees, different user archetypes respond differently. "
            "Retail users abandon first; whales absorb the shock; arb bots switch to L2."
        )

        col_a, col_b = st.columns([1, 2])
        with col_a:
            pqc_algo = st.selectbox(
                "PQC Algorithm",
                ["ML-DSA-65", "Falcon-512", "ML-DSA-87", "SLH-DSA-128s", "SLH-DSA-128f"],
                key="econ_algo",
            )
            st.markdown("#### Agent Mix")
            mix_chain = CHAIN_AGENT_MIX.get(chain, CHAIN_AGENT_MIX["ethereum"])
            for agent, frac in mix_chain.items():
                st.caption(f"{agent.replace('_', ' ').title()}: {frac*100:.0f}%")

        with col_b:
            st.plotly_chart(
                _demand_destruction_chart(chain, pqc_algo),
                use_container_width=True,
            )

        # ------------------------------------------------------------------
        # Per-agent breakdown at a given fee multiple
        # ------------------------------------------------------------------
        st.subheader("Agent Response at a Specific Fee Level")
        fee_mult = st.slider("Fee Multiplier vs Baseline", 1.0, 20.0, 5.0, step=0.5)
        pool     = AgentPool(chain=chain, pool_size=500, seed=42)
        demand   = pool.simulate_block_demand(
            current_fee_rate  = fee_mult,
            baseline_fee_rate = 1.0,
            sig_algorithm     = pqc_algo,
            blocks_elevated   = 100,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Submitted",      f"{demand['txs_submitted']}")
        c2.metric("Abandoned",      f"{demand['txs_abandoned']}")
        c3.metric("Batched",        f"{demand['txs_batched']}")
        c4.metric("L2 Migrations",  f"{demand['l2_migrations']}")
        st.caption(
            f"Demand reduction: **{demand['demand_reduction_pct']:.1f}%** vs baseline. "
            f"Submission rate: **{demand['submission_rate']*100:.0f}%**."
        )
