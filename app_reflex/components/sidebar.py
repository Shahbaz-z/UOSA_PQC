"""Sidebar component with educational content."""

from __future__ import annotations

import reflex as rx

from app_reflex.state.base import AppState
from app_reflex.styles.theme import COLORS


def sidebar() -> rx.Component:
    """Create the educational sidebar."""
    return rx.box(
        rx.vstack(
            # Title
            rx.hstack(
                rx.text("Blockchain QR Educator", size="5", weight="bold"),
                spacing="2",
                align="center",
            ),
            rx.divider(),

            # Mock mode indicator
            rx.cond(
                AppState.mock_mode,
                rx.callout(
                    "Mock mode -- liboqs not available. Sizes accurate; timing synthetic.",
                    icon="triangle-alert",
                    color="orange",
                    size="1",
                ),
                rx.callout(
                    "Real mode -- liboqs detected.",
                    icon="check",
                    color="green",
                    size="1",
                ),
            ),

            rx.divider(),

            # Quick reference sections
            rx.accordion.root(
                rx.accordion.item(
                    header="What is PQC?",
                    content=rx.text(
                        "Post-Quantum Cryptography (PQC) refers to cryptographic algorithms "
                        "designed to resist attacks from quantum computers. Unlike current "
                        "elliptic-curve and RSA schemes, PQC algorithms are based on "
                        "mathematical problems believed to be hard for quantum computers.",
                        size="1",
                    ),
                    value="pqc",
                ),
                rx.accordion.item(
                    header="Why does this matter for blockchains?",
                    content=rx.text(
                        "Blockchain security relies on digital signatures. Current schemes "
                        "(ECDSA, Ed25519) will be vulnerable to quantum attacks. PQC "
                        "signatures are larger, impacting transaction throughput. This tool "
                        "helps visualize that impact.",
                        size="1",
                    ),
                    value="blockchain",
                ),
                rx.accordion.item(
                    header="NIST Standards",
                    content=rx.vstack(
                        rx.text("FIPS 203: ML-KEM (Kyber)", size="1"),
                        rx.text("FIPS 204: ML-DSA (Dilithium)", size="1"),
                        rx.text("FIPS 205: SLH-DSA (SPHINCS+)", size="1"),
                        rx.text("Pending: FN-DSA (Falcon)", size="1"),
                        spacing="1",
                    ),
                    value="nist",
                ),
                rx.accordion.item(
                    header="Security Levels",
                    content=rx.vstack(
                        rx.text("Level 1: AES-128 equivalent", size="1"),
                        rx.text("Level 2: SHA-256 equivalent", size="1"),
                        rx.text("Level 3: AES-192 equivalent", size="1"),
                        rx.text("Level 5: AES-256 equivalent", size="1"),
                        spacing="1",
                    ),
                    value="levels",
                ),
                type="multiple",
                width="100%",
            ),

            rx.divider(),

            # Navigation
            rx.text("NAVIGATION", size="1", color=COLORS["text_muted"]),
            rx.vstack(
                rx.text("1. Block-Space -- Chain impact analysis", size="1"),
                rx.text("2. Compare -- Side-by-side algorithms", size="1"),
                spacing="1",
                align="start",
            ),

            spacing="4",
            width="100%",
            padding="4",
        ),
        width="280px",
        height="100vh",
        background=COLORS["surface"],
        border_right=f"1px solid {COLORS['border']}",
        position="fixed",
        left="0",
        top="0",
        overflow_y="auto",
    )
