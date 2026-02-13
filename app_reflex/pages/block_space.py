"""Block-Space Visualizer page."""

from __future__ import annotations

import reflex as rx

from app_reflex.state.block_space import BlockSpaceState
from app_reflex.components.charts import (
    block_space_chart_component,
    throughput_chart_component,
    signature_size_chart_component,
)
from app_reflex.styles.theme import COLORS


def solana_presets() -> rx.Component:
    """Solana preset buttons."""
    return rx.hstack(
        rx.button(
            "Theoretical Max",
            on_click=BlockSpaceState.preset_solana_theoretical,
            variant="outline",
            size="1",
        ),
        rx.button(
            "Realistic (70%)",
            on_click=BlockSpaceState.preset_solana_realistic,
            variant="outline",
            size="1",
        ),
        rx.button(
            "High Activity",
            on_click=BlockSpaceState.preset_solana_high_activity,
            variant="outline",
            size="1",
        ),
        rx.button(
            "High Throughput",
            on_click=BlockSpaceState.preset_solana_high_throughput,
            variant="outline",
            size="1",
        ),
        spacing="2",
        wrap="wrap",
    )


def bitcoin_presets() -> rx.Component:
    """Bitcoin preset buttons."""
    return rx.hstack(
        rx.button(
            "Default (4 MWU)",
            on_click=BlockSpaceState.preset_bitcoin_default,
            variant="outline",
            size="1",
        ),
        rx.button(
            "Larger (8 MWU)",
            on_click=BlockSpaceState.preset_bitcoin_larger,
            variant="outline",
            size="1",
        ),
        rx.button(
            "Faster (2.5 min)",
            on_click=BlockSpaceState.preset_bitcoin_faster,
            variant="outline",
            size="1",
        ),
        spacing="2",
        wrap="wrap",
    )


def ethereum_presets() -> rx.Component:
    """Ethereum gas limit preset buttons."""
    return rx.hstack(
        rx.button(
            "30M (2024)",
            on_click=BlockSpaceState.preset_ethereum_2024,
            variant="outline",
            size="1",
        ),
        rx.button(
            "36M (2025)",
            on_click=BlockSpaceState.preset_ethereum_2025,
            variant="outline",
            size="1",
        ),
        rx.button(
            "60M (Q1 2026)",
            on_click=BlockSpaceState.preset_ethereum_2026_q1,
            variant="outline",
            size="1",
        ),
        rx.button(
            "80M (Q2 2026)",
            on_click=BlockSpaceState.preset_ethereum_2026_q2,
            variant="outline",
            size="1",
        ),
        rx.button(
            "180M (Target)",
            on_click=BlockSpaceState.preset_ethereum_target,
            variant="outline",
            size="1",
        ),
        spacing="2",
        wrap="wrap",
    )


def solana_params() -> rx.Component:
    """Solana parameter inputs."""
    return rx.vstack(
        rx.text("Vote Transaction Overhead (%)", size="2", weight="medium"),
        rx.slider(
            default_value=[0],
            min=0,
            max=85,
            step=5,
            on_value_commit=BlockSpaceState.set_sol_vote_pct,
            width="100%",
        ),
        rx.text(BlockSpaceState.available_space_info, size="1", color=COLORS["text_muted"]),

        rx.text("Block Size (bytes)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.sol_block_size.to_string(),
            on_change=BlockSpaceState.set_sol_block_size,
            type="number",
            width="100%",
        ),

        rx.text("Base TX Overhead (bytes)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.sol_base_overhead.to_string(),
            on_change=BlockSpaceState.set_sol_base_overhead,
            type="number",
            width="100%",
        ),

        rx.text("Slot Time (ms)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.sol_slot_time.to_string(),
            on_change=BlockSpaceState.set_sol_slot_time,
            type="number",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def bitcoin_params() -> rx.Component:
    """Bitcoin parameter inputs."""
    return rx.vstack(
        rx.text("Block Weight (WU)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.btc_block_weight.to_string(),
            on_change=BlockSpaceState.set_btc_block_weight,
            type="number",
            width="100%",
        ),

        rx.text("Base TX Overhead (bytes)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.btc_base_overhead.to_string(),
            on_change=BlockSpaceState.set_btc_base_overhead,
            type="number",
            width="100%",
        ),

        rx.text("Block Time (ms)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.btc_block_time.to_string(),
            on_change=BlockSpaceState.set_btc_block_time,
            type="number",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def ethereum_params() -> rx.Component:
    """Ethereum parameter inputs."""
    return rx.vstack(
        rx.text("Block Gas Limit", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.eth_gas_limit.to_string(),
            on_change=BlockSpaceState.set_eth_gas_limit,
            type="number",
            width="100%",
        ),

        rx.text("Base TX Overhead (bytes)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.eth_base_overhead.to_string(),
            on_change=BlockSpaceState.set_eth_base_overhead,
            type="number",
            width="100%",
        ),

        rx.text("Block Time (ms)", size="2", weight="medium"),
        rx.input(
            value=BlockSpaceState.eth_block_time.to_string(),
            on_change=BlockSpaceState.set_eth_block_time,
            type="number",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def results_table() -> rx.Component:
    """Display analysis results in a table."""
    return rx.data_table(
        data=BlockSpaceState.analysis_results,
        columns=[
            {"header": "Scheme", "accessor": "scheme"},
            {"header": "Sig (B)", "accessor": "sig_size"},
            {"header": "TX (B)", "accessor": "tx_size"},
            {"header": "Txs/Block", "accessor": "txs_per_block"},
            {"header": "TPS", "accessor": "tps"},
            {"header": "vs Baseline", "accessor": "vs_baseline"},
        ],
        pagination=rx.data_table.pagination(page_size=10),
    )


def key_findings() -> rx.Component:
    """Display key findings metrics."""
    return rx.hstack(
        rx.card(
            rx.vstack(
                rx.text("Baseline TPS", size="1", color=COLORS["text_muted"]),
                rx.text(BlockSpaceState.baseline_tps.to_string(), size="6", weight="bold"),
                rx.text(BlockSpaceState.baseline_scheme, size="1"),
                spacing="1",
                align="center",
            ),
            width="200px",
        ),
        rx.card(
            rx.vstack(
                rx.text("Falcon-512 TPS", size="1", color=COLORS["text_muted"]),
                rx.text(BlockSpaceState.falcon_tps.to_string(), size="6", weight="bold"),
                rx.text(
                    rx.text.span(BlockSpaceState.falcon_vs_baseline.to_string(), color=COLORS["secondary"]),
                    "% of baseline",
                    size="1",
                ),
                spacing="1",
                align="center",
            ),
            width="200px",
        ),
        rx.card(
            rx.vstack(
                rx.text("ML-DSA-65 TPS", size="1", color=COLORS["text_muted"]),
                rx.text(BlockSpaceState.ml_dsa_tps.to_string(), size="6", weight="bold"),
                rx.text("NIST recommended", size="1"),
                spacing="1",
                align="center",
            ),
            width="200px",
        ),
        spacing="4",
        wrap="wrap",
    )


def block_space_page() -> rx.Component:
    """Block-Space Visualizer page content."""
    return rx.vstack(
        # Header
        rx.heading("Block-Space Impact Analysis", size="7"),
        rx.text(
            "Explore how replacing classical signatures with PQC alternatives affects blockchain throughput.",
            color=COLORS["text_muted"],
        ),

        # Chain selector
        rx.hstack(
            rx.text("Select Blockchain:", weight="medium"),
            rx.radio_group(
                ["Solana", "Bitcoin", "Ethereum"],
                default_value="Solana",
                on_change=BlockSpaceState.set_chain,
                direction="row",
            ),
            spacing="4",
            align="center",
        ),

        # Multi-signer slider
        rx.hstack(
            rx.text("Number of Signers:", weight="medium"),
            rx.slider(
                default_value=[1],
                min=1,
                max=5,
                step=1,
                on_value_commit=BlockSpaceState.set_num_signers,
                width="200px",
            ),
            rx.badge(BlockSpaceState.num_signers.to_string()),
            spacing="4",
            align="center",
        ),

        rx.divider(),

        # Chain-specific info
        rx.callout(
            BlockSpaceState.chain_info,
            icon="info",
            size="1",
        ),

        # Presets section
        rx.text("Quick Presets", weight="bold", size="4"),
        rx.cond(
            BlockSpaceState.chain == "Solana",
            solana_presets(),
            rx.cond(
                BlockSpaceState.chain == "Bitcoin",
                bitcoin_presets(),
                ethereum_presets(),
            ),
        ),

        # Two-column layout: Parameters + Results
        rx.hstack(
            # Parameters column
            rx.box(
                rx.vstack(
                    rx.text("Model Parameters", weight="bold", size="4"),
                    rx.cond(
                        BlockSpaceState.chain == "Solana",
                        solana_params(),
                        rx.cond(
                            BlockSpaceState.chain == "Bitcoin",
                            bitcoin_params(),
                            ethereum_params(),
                        ),
                    ),
                    spacing="4",
                    width="100%",
                ),
                width="300px",
                padding="4",
                background=COLORS["surface"],
                border_radius="8px",
            ),

            # Results column
            rx.box(
                rx.vstack(
                    rx.text("Analysis Results", weight="bold", size="4"),
                    results_table(),
                    spacing="4",
                    width="100%",
                ),
                flex="1",
                padding="4",
            ),
            spacing="6",
            width="100%",
            align="start",
        ),

        rx.divider(),

        # Key findings
        rx.text("Key Findings", weight="bold", size="4"),
        key_findings(),

        rx.callout(
            "Falcon-512 signatures (666 B) are significantly smaller than ML-DSA-44 (2,420 B), "
            "making Falcon the most block-space efficient PQC signature scheme for blockchain applications.",
            icon="lightbulb",
            color="blue",
        ),

        rx.divider(),

        # Charts section
        rx.text("Visualizations", weight="bold", size="4"),
        rx.grid(
            rx.box(
                block_space_chart_component(BlockSpaceState.analysis_results, BlockSpaceState.chain),
                padding="4",
            ),
            rx.box(
                throughput_chart_component(BlockSpaceState.analysis_results, BlockSpaceState.chain),
                padding="4",
            ),
            columns="2",
            spacing="4",
            width="100%",
        ),
        rx.box(
            signature_size_chart_component(BlockSpaceState.analysis_results, BlockSpaceState.chain),
            padding="4",
            width="100%",
        ),

        spacing="6",
        width="100%",
        padding="6",
    )
