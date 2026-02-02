"""Tests for blockchain.solana_model – Solana and Bitcoin block-space analysis."""

import pytest

from blockchain.solana_model import (
    analyze_block_space,
    analyze_solana_block_space,
    analyze_bitcoin_block_space,
    compare_all,
    compare_all_solana,
    compare_all_bitcoin,
    SIGNATURE_SIZES,
    SOLANA_SIG_TYPES,
    BITCOIN_SIG_TYPES,
    SOLANA_BLOCK_SIZE_BYTES,
    SOLANA_BASE_TX_OVERHEAD,
    BITCOIN_BLOCK_WEIGHT_LIMIT,
    BITCOIN_BASE_TX_OVERHEAD,
    BITCOIN_WITNESS_DISCOUNT,
)


class TestSolanaBlockSpace:
    def test_ed25519_baseline(self):
        result = analyze_solana_block_space("Ed25519")
        assert result.signature_bytes == 64
        assert result.tx_size_bytes == SOLANA_BASE_TX_OVERHEAD + 64
        assert result.relative_to_baseline == 1.0

    def test_dilithium3_smaller_throughput(self):
        ed = analyze_solana_block_space("Ed25519")
        d3 = analyze_solana_block_space("Dilithium3")
        assert d3.txs_per_block < ed.txs_per_block
        assert d3.relative_to_baseline < 1.0

    def test_falcon_better_than_dilithium(self):
        f512 = analyze_solana_block_space("Falcon-512")
        d2 = analyze_solana_block_space("Dilithium2")
        assert f512.txs_per_block > d2.txs_per_block

    def test_txs_per_block_calculation(self):
        result = analyze_solana_block_space("Ed25519")
        expected = SOLANA_BLOCK_SIZE_BYTES // (SOLANA_BASE_TX_OVERHEAD + 64)
        assert result.txs_per_block == expected

    def test_signature_overhead_percentage(self):
        result = analyze_solana_block_space("Dilithium5")
        expected_pct = round(4595 / (SOLANA_BASE_TX_OVERHEAD + 4595) * 100, 2)
        assert result.signature_overhead_pct == expected_pct

    @pytest.mark.parametrize("sig_type", SOLANA_SIG_TYPES)
    def test_all_signature_types(self, sig_type: str):
        result = analyze_solana_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0
        assert 0 < result.block_utilization_pct <= 100

    def test_custom_parameters(self):
        result = analyze_solana_block_space("Ed25519", block_size=1_000_000, base_tx_overhead=100)
        expected_txs = 1_000_000 // (100 + 64)
        assert result.txs_per_block == expected_txs

    def test_ml_dsa_matches_dilithium(self):
        d3 = analyze_solana_block_space("Dilithium3")
        ml65 = analyze_solana_block_space("ML-DSA-65")
        assert d3.signature_bytes == ml65.signature_bytes
        assert d3.txs_per_block == ml65.txs_per_block


class TestSolanaCompareAll:
    def test_returns_all_schemes(self):
        comp = compare_all_solana()
        assert len(comp.analyses) == len(SOLANA_SIG_TYPES)

    def test_baseline_is_ed25519(self):
        comp = compare_all_solana()
        assert comp.baseline.signature_type == "Ed25519"
        assert comp.chain == "Solana"

    def test_all_have_positive_tps(self):
        comp = compare_all_solana()
        for a in comp.analyses:
            assert a.throughput_tps > 0


class TestBitcoinBlockSpace:
    def test_ecdsa_baseline(self):
        result = analyze_bitcoin_block_space("ECDSA")
        assert result.signature_bytes == 72
        assert result.relative_to_baseline == 1.0

    def test_segwit_discount_applied(self):
        """Verify SegWit discount: witness data at 1x, non-witness at 4x."""
        result = analyze_bitcoin_block_space("ECDSA")
        expected_weight = (BITCOIN_BASE_TX_OVERHEAD * BITCOIN_WITNESS_DISCOUNT) + 72 + 33
        expected_txs = BITCOIN_BLOCK_WEIGHT_LIMIT // expected_weight
        assert result.txs_per_block == expected_txs

    def test_falcon_better_than_dilithium(self):
        f512 = analyze_bitcoin_block_space("Falcon-512")
        d2 = analyze_bitcoin_block_space("Dilithium2")
        assert f512.txs_per_block > d2.txs_per_block

    def test_pqc_reduces_throughput(self):
        ecdsa = analyze_bitcoin_block_space("ECDSA")
        d3 = analyze_bitcoin_block_space("Dilithium3")
        assert d3.txs_per_block < ecdsa.txs_per_block
        assert d3.relative_to_baseline < 1.0

    @pytest.mark.parametrize("sig_type", BITCOIN_SIG_TYPES)
    def test_all_signature_types(self, sig_type: str):
        result = analyze_bitcoin_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0

    def test_vsize_is_weight_div_4(self):
        result = analyze_bitcoin_block_space("ECDSA")
        expected_weight = (BITCOIN_BASE_TX_OVERHEAD * 4) + 72 + 33
        assert result.tx_size_bytes == round(expected_weight / 4)


class TestBitcoinCompareAll:
    def test_returns_all_schemes(self):
        comp = compare_all_bitcoin()
        assert len(comp.analyses) == len(BITCOIN_SIG_TYPES)

    def test_baseline_is_ecdsa(self):
        comp = compare_all_bitcoin()
        assert comp.baseline.signature_type == "ECDSA"
        assert comp.chain == "Bitcoin"

    def test_all_have_positive_tps(self):
        comp = compare_all_bitcoin()
        for a in comp.analyses:
            assert a.throughput_tps > 0


class TestBackwardsCompatibility:
    def test_analyze_block_space_alias(self):
        result = analyze_block_space("Ed25519")
        assert result.signature_bytes == 64
        assert result.relative_to_baseline == 1.0

    def test_compare_all_alias(self):
        comp = compare_all()
        assert comp.baseline.signature_type == "Ed25519"
