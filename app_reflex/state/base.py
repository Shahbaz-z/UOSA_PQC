"""Base application state."""

from __future__ import annotations

import reflex as rx
from pqc_lib.mock import MOCK_MODE


class AppState(rx.State):
    """Root application state with global settings."""

    # Mock mode detection
    mock_mode: bool = MOCK_MODE

    # Active tab tracking
    active_tab: str = "block_space"

    def set_active_tab(self, tab: str):
        """Set the active tab."""
        self.active_tab = tab

    @rx.var
    def mock_mode_message(self) -> str:
        """Get mock mode status message."""
        if self.mock_mode:
            return (
                "Mock mode -- liboqs not available. "
                "Artifact sizes are NIST-accurate; timing is synthetic."
            )
        return "Real mode -- liboqs detected. Full cryptographic operations available."

    @rx.var
    def mock_mode_color(self) -> str:
        """Get color for mock mode indicator."""
        return "orange" if self.mock_mode else "green"
