"""Tab rendering modules for the Streamlit application."""

from app.tabs.overview import render as render_overview
from app.tabs.block_space import render as render_block_space
from app.tabs.comparison import render as render_comparison
from app.tabs.pqc_shock_sim import render as render_pqc_shock

__all__ = [
    "render_overview",
    "render_block_space",
    "render_comparison",
    "render_pqc_shock",
]
