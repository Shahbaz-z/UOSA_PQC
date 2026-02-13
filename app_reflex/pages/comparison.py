"""Side-by-Side Comparison page."""

from __future__ import annotations

import reflex as rx

from app_reflex.state.comparison import ComparisonState
from app_reflex.components.charts import comparison_chart_component
from app_reflex.styles.theme import COLORS


def algorithm_selector() -> rx.Component:
    """Algorithm selection with checkboxes."""
    return rx.vstack(
        rx.hstack(
            rx.text("Quick Select:", weight="medium"),
            rx.button(
                "Minimal",
                on_click=ComparisonState.select_minimal,
                variant="outline",
                size="1",
            ),
            rx.button(
                "Lattice-based",
                on_click=ComparisonState.select_lattice_based,
                variant="outline",
                size="1",
            ),
            rx.button(
                "All PQC",
                on_click=ComparisonState.select_all_pqc,
                variant="outline",
                size="1",
            ),
            spacing="2",
        ),
        rx.text("Selected Algorithms", weight="medium", size="2"),
        rx.flex(
            rx.foreach(
                ComparisonState.available_algorithms,
                lambda algo: rx.checkbox(
                    algo,
                    checked=ComparisonState.selected_algos.contains(algo),
                    on_change=lambda _: ComparisonState.toggle_algorithm(algo),
                    size="1",
                ),
            ),
            wrap="wrap",
            spacing="3",
        ),
        spacing="3",
        width="100%",
    )


def comparison_controls() -> rx.Component:
    """Comparison run controls."""
    return rx.hstack(
        rx.vstack(
            rx.text("Test Message", weight="medium", size="2"),
            rx.input(
                value=ComparisonState.compare_msg,
                on_change=ComparisonState.set_compare_msg,
                placeholder="Enter message to sign...",
                width="400px",
            ),
            spacing="2",
        ),
        rx.button(
            rx.cond(
                ComparisonState.is_running,
                rx.hstack(rx.spinner(size="1"), rx.text("Running...")),
                rx.text("Run Comparison"),
            ),
            on_click=ComparisonState.run_comparison,
            disabled=~ComparisonState.enough_selected | ComparisonState.is_running,
            size="3",
            color_scheme="blue",
        ),
        spacing="4",
        align="end",
    )


def progress_indicator() -> rx.Component:
    """Show progress during comparison."""
    return rx.cond(
        ComparisonState.is_running,
        rx.vstack(
            rx.progress(value=ComparisonState.progress, width="100%"),
            rx.text(
                rx.text.span("Processing: ", color=COLORS["text_muted"]),
                rx.text.span(ComparisonState.current_algo, weight="bold"),
                size="1",
            ),
            spacing="2",
            width="100%",
        ),
        rx.fragment(),
    )


def quick_stats() -> rx.Component:
    """Quick overview stats from comparison results."""
    return rx.cond(
        ComparisonState.has_results,
        rx.hstack(
            rx.card(
                rx.vstack(
                    rx.text("Smallest Signature", size="1", color=COLORS["text_muted"]),
                    rx.text(ComparisonState.smallest_signature, size="4", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                width="180px",
            ),
            rx.card(
                rx.vstack(
                    rx.text("Fastest Sign", size="1", color=COLORS["text_muted"]),
                    rx.text(ComparisonState.fastest_sign, size="4", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                width="180px",
            ),
            rx.card(
                rx.vstack(
                    rx.text("Fastest Verify", size="1", color=COLORS["text_muted"]),
                    rx.text(ComparisonState.fastest_verify, size="4", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                width="180px",
            ),
            spacing="4",
            wrap="wrap",
        ),
        rx.fragment(),
    )


def results_table() -> rx.Component:
    """Detailed comparison results table."""
    return rx.cond(
        ComparisonState.has_results,
        rx.vstack(
            rx.text("Detailed Comparison", weight="bold", size="4"),
            rx.data_table(
                data=ComparisonState.results_list,
                columns=[
                    {"header": "Algorithm", "accessor": "algorithm"},
                    {"header": "PK (B)", "accessor": "pk_size"},
                    {"header": "Sig (B)", "accessor": "sig_size"},
                    {"header": "Keygen (ms)", "accessor": "keygen_ms"},
                    {"header": "Sign (ms)", "accessor": "sign_ms"},
                    {"header": "Verify (ms)", "accessor": "verify_ms"},
                    {"header": "vs Ed25519", "accessor": "vs_ed25519"},
                ],
            ),
            spacing="4",
            width="100%",
        ),
        rx.fragment(),
    )


def comparison_page() -> rx.Component:
    """Side-by-Side Comparison page content."""
    return rx.vstack(
        # Header
        rx.heading("Side-by-Side Algorithm Comparison", size="7"),
        rx.text(
            "Compare signature sizes and performance across multiple algorithms.",
            color=COLORS["text_muted"],
        ),

        # Instructions
        rx.accordion.root(
            rx.accordion.item(
                header="How to use this tool",
                content=rx.vstack(
                    rx.text("1. Select 2 or more signature algorithms to compare"),
                    rx.text("2. Optionally change the test message"),
                    rx.text("3. Click 'Run Comparison' to see the results"),
                    spacing="2",
                ),
                value="howto",
            ),
            type="single",
            collapsible=True,
            width="100%",
        ),

        rx.divider(),

        # Algorithm selector
        algorithm_selector(),

        rx.divider(),

        # Controls
        comparison_controls(),

        # Progress
        progress_indicator(),

        rx.divider(),

        # Quick stats
        quick_stats(),

        # Results table
        results_table(),

        # Chart
        rx.cond(
            ComparisonState.has_results,
            rx.vstack(
                rx.text("Visual Comparison", weight="bold", size="4"),
                comparison_chart_component(ComparisonState.compare_results),
                spacing="4",
                width="100%",
            ),
            rx.fragment(),
        ),

        spacing="6",
        width="100%",
        padding="6",
    )
