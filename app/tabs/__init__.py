"""Tab rendering modules for the Streamlit application."""

from app.tabs.overview import render as render_overview
from app.tabs.block_space import render as render_block_space
from app.tabs.comparison import render as render_comparison
from app.tabs.pqc_shock_sim import render as render_pqc_shock
from app.tabs.chain_architecture import render as render_chain_architecture
from app.tabs.fee_economics import render as render_fee_economics
from app.tabs.risk_dashboard import render as render_risk_dashboard

__all__ = [
    "render_overview",
    "render_block_space",
    "render_comparison",
    "render_pqc_shock",
    "render_chain_architecture",
    "render_fee_economics",
    "render_risk_dashboard",
]
