"""Shared helper functions and constants for the Streamlit UI.

Centralises utilities that were previously duplicated across
block_space.py, comparison.py, and overview.py and pqc_shock_sim.py.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Chain brand colours (used across cross-chain and shock tabs)
# ---------------------------------------------------------------------------
CHAIN_COLORS: dict[str, str] = {
    "Solana": "#9945FF",
    "Ethereum": "#627EEA",
    "Bitcoin": "#F7931A",
}


# ---------------------------------------------------------------------------
# Shared formatting / badge helpers
# ---------------------------------------------------------------------------
def format_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1024:
        return f"{n:,} B ({n / 1024:.1f} KB)"
    return f"{n:,} B"


def throughput_impact_category(ratio: float) -> str:
    """Categorize throughput impact for educational display."""
    if ratio >= 0.9:
        return ":green[Minimal Impact]"
    elif ratio >= 0.7:
        return ":orange[Moderate Impact]"
    elif ratio >= 0.4:
        return ":red[Significant Impact]"
    else:
        return ":red[Severe Impact]"


def threat_badge(level: str) -> str:
    """Return a coloured threat-level badge in Streamlit markdown."""
    colors = {
        "HIGH": "red",
        "MODERATE-HIGH": "orange",
        "MODERATE": "orange",
        "LOW": "green",
    }
    return f":{colors.get(level, 'gray')}[**{level}**]"
