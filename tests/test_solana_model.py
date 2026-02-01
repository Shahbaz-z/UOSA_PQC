"""Tests for blockchain.solana_model – Solana block-space analysis."""

import pytest

from blockchain.solana_model import (
    analyze_block_space,
    compare_all,
    SIGNATURE_SIZES,
    SOLANA_BLOCK_SIZE_BYTES,
    SOLANA_BASE_TX_OVERHEAD,
)


class TestAnalyzeBlockSpace:
    def test_ed25519_baseline(self):
        result = analyze_block_space("Ed25519")
        assert result.signature_bytes == 64
        assert result.tx_size_bytes == SOLANA_BASE_TX_OVERHEAD + 64
        assert result.relative_to_ed25519 == 1.0

    def test_dilithium3_smaller_throughput(self):
        ed = analyze_block_space("Ed25519")
        d3 = analyze_block_space("Dilithium3")
        assert d3.txs_per_block < ed.txs_per_block
        assert d3.relative_to_ed25519 < 1.0

    def test_txs_per_block_calculation(self):
        result = analyze_block_space("Ed25519")
        expected = SOLANA_BLOCK_SIZE_BYTES // (SOLANA_BASE_TX_OVERHEAD + 64)
        assert result.txs_per_block == expected

    def test_signature_overhead_percentage(self):
        result = analyze_block_space("Dilithium5")
        expected_pct = round(4595 / (SOLANA_BASE_TX_OVERHEAD + 4595) * 100, 2)
        assert result.signature_overhead_pct == expected_pct

    @pytest.mark.parametrize("sig_type", list(SIGNATURE_SIZES.keys()))
    def test_all_signature_types(self, sig_type: str):
        result = analyze_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0
        assert 0 < result.block_utilization_pct <= 100

    def test_custom_parameters(self):
        result = analyze_block_space("Ed25519", block_size=1_000_000, base_tx_overhead=100)
        expected_txs = 1_000_000 // (100 + 64)
        assert result.txs_per_block == expected_txs


class TestCompareAll:
    def test_returns_all_schemes(self):
        comp = compare_all()
        assert len(comp.analyses) == len(SIGNATURE_SIZES)

    def test_baseline_is_ed25519(self):
        comp = compare_all()
        assert comp.baseline.signature_type == "Ed25519"

    def test_all_have_positive_tps(self):
        comp = compare_all()
        for a in comp.analyses:
            assert a.throughput_tps > 0
