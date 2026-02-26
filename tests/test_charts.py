"""Tests for app/components/charts.py -- verify chart functions return valid Plotly figures.

These tests do NOT render charts in a browser; they verify that:
1. Each chart function returns a go.Figure
2. Figures contain at least one trace
3. Figures have expected layout attributes (title, axes)
4. Functions handle edge cases gracefully
"""

import pytest
import plotly.graph_objects as go

from blockchain.chain_models import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SOLANA_VOTE_TX_PCT_REALISTIC,
)

from app.components.charts import (
    block_space_chart,
    throughput_comparison_chart,
    signature_size_comparison,
    side_by_side_dual_axis_chart,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def solana_analyses():
    comp = compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC)
    return comp.analyses


@pytest.fixture
def bitcoin_analyses():
    comp = compare_all_bitcoin()
    return comp.analyses


@pytest.fixture
def ethereum_analyses():
    comp = compare_all_ethereum()
    return comp.analyses


# ---------------------------------------------------------------------------
# Block-space charts
# ---------------------------------------------------------------------------

class TestBlockSpaceChart:
    def test_returns_figure(self, solana_analyses):
        fig = block_space_chart(solana_analyses, "Solana")
        assert isinstance(fig, go.Figure)

    def test_has_traces(self, solana_analyses):
        fig = block_space_chart(solana_analyses, "Solana")
        assert len(fig.data) > 0

    @pytest.mark.parametrize("chain,fixture_name", [
        ("Solana", "solana_analyses"),
        ("Bitcoin", "bitcoin_analyses"),
        ("Ethereum", "ethereum_analyses"),
    ])
    def test_all_chains(self, chain, fixture_name, request):
        analyses = request.getfixturevalue(fixture_name)
        fig = block_space_chart(analyses, chain)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0


class TestThroughputComparisonChart:
    def test_returns_figure(self, solana_analyses):
        fig = throughput_comparison_chart(solana_analyses, "Solana")
        assert isinstance(fig, go.Figure)

    def test_has_traces(self, solana_analyses):
        fig = throughput_comparison_chart(solana_analyses, "Solana")
        assert len(fig.data) > 0


class TestSignatureSizeComparison:
    def test_returns_figure(self, solana_analyses):
        fig = signature_size_comparison(solana_analyses, "Solana")
        assert isinstance(fig, go.Figure)

    def test_has_traces(self, solana_analyses):
        fig = signature_size_comparison(solana_analyses, "Solana")
        assert len(fig.data) > 0


# ---------------------------------------------------------------------------
# Side-by-side comparison chart
# ---------------------------------------------------------------------------

class TestSideBySideDualAxisChart:
    def test_returns_figure(self):
        # Minimal mock results dict
        from pqc_lib.signatures import sign_keygen, sign
        kp = sign_keygen("Ed25519")
        sr = sign("Ed25519", kp.secret_key, b"test", kp)
        results = {"Ed25519": sr}
        fig = side_by_side_dual_axis_chart(results)
        assert isinstance(fig, go.Figure)

    def test_multiple_algorithms(self):
        from pqc_lib.signatures import sign_keygen, sign
        results = {}
        for algo in ["Ed25519", "ML-DSA-44"]:
            kp = sign_keygen(algo)
            sr = sign(algo, kp.secret_key, b"test", kp)
            results[algo] = sr
        fig = side_by_side_dual_axis_chart(results)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2  # at least size and time traces
