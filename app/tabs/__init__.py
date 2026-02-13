"""Tab rendering modules for the Streamlit application."""

from app.tabs.block_space import render as render_block_space
from app.tabs.comparison import render as render_comparison
from app.tabs.cross_chain import render as render_cross_chain
from app.tabs.zk_proofs import render as render_zk_proofs
from app.tabs.qr_score import render as render_qr_score

__all__ = [
    "render_block_space",
    "render_comparison",
    "render_cross_chain",
    "render_zk_proofs",
    "render_qr_score",
]
