"""Blockchain Quantum Resistance Educator - Reflex Application.

Main entry point for the Reflex application.
"""

from __future__ import annotations

import reflex as rx

from app_reflex.state.base import AppState
from app_reflex.state.block_space import BlockSpaceState
from app_reflex.state.comparison import ComparisonState
from app_reflex.components.sidebar import sidebar
from app_reflex.pages.block_space import block_space_page
from app_reflex.pages.comparison import comparison_page
from app_reflex.styles.theme import COLORS


def main_content() -> rx.Component:
    """Main content area with tabs."""
    return rx.box(
        rx.vstack(
            # Header
            rx.hstack(
                rx.heading("Blockchain Quantum Resistance Educator", size="8"),
                rx.spacer(),
                rx.badge(
                    rx.cond(
                        AppState.mock_mode,
                        "Mock Mode",
                        "Real Mode",
                    ),
                    color_scheme=rx.cond(AppState.mock_mode, "orange", "green"),
                ),
                width="100%",
                padding_bottom="4",
            ),
            rx.text(
                "An interactive educational tool for exploring how post-quantum cryptography "
                "affects blockchain transaction throughput on Solana, Bitcoin, and Ethereum.",
                color=COLORS["text_muted"],
                size="2",
            ),

            rx.divider(),

            # Tab navigation
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Block-Space Visualizer", value="block_space"),
                    rx.tabs.trigger("Side-by-Side Comparison", value="comparison"),
                ),
                rx.tabs.content(
                    block_space_page(),
                    value="block_space",
                ),
                rx.tabs.content(
                    comparison_page(),
                    value="comparison",
                ),
                default_value="block_space",
                width="100%",
            ),

            spacing="4",
            width="100%",
            padding="6",
        ),
        margin_left="280px",  # Offset for sidebar
        min_height="100vh",
        background=COLORS["background"],
    )


def index() -> rx.Component:
    """Main page layout."""
    return rx.box(
        sidebar(),
        main_content(),
        width="100%",
        min_height="100vh",
        background=COLORS["background"],
        color=COLORS["text"],
    )


# Create the app
app = rx.App(
    theme=rx.theme(
        appearance="dark",
        accent_color="blue",
        radius="medium",
    ),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
    ],
)

# Add the main page
app.add_page(index, route="/", title="Blockchain QR Educator")
