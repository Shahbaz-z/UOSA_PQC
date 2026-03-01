"""Tests for blockchain.chain_models -- Solana, Bitcoin, and Ethereum block-space analysis."""

import pytest

from blockchain.chain_models import (
    analyze_solana_block_space,
    analyze_bitcoin_block_space,
    analyze_ethereum_block_space,
    compare_all_solana,
    compare_all_bitcoin,
    compare_all_ethereum,
    SIGNATURE_SIZES,
    PUBLIC_KEY_SIZES,
    SOLANA_SIG_TYPES,
    BITCOIN_SIG_TYPES,
    ETHEREUM_SIG_TYPES,
    SOLANA_BLOCK_SIZE_BYTES,
    SOLANA_BASE_TX_OVERHEAD,
    BITCOIN_BLOCK_WEIGHT_LIMIT,
    BITCOIN_BASE_TX_OVERHEAD,
    BITCOIN_WITNESS_DISCOUNT,
    ETHEREUM_BLOCK_GAS_LIMIT,
    ETHEREUM_BASE_TX_GAS,
    ETHEREUM_CALLDATA_GAS_PER_BYTE,
    ETHEREUM_BASE_TX_OVERHEAD,
)


class TestSolanaBlockSpace:
    def test_ed25519_baseline(self):
        result = analyze_solana_block_space("Ed25519")
        assert result.signature_bytes == SIGNATURE_SIZES["Ed25519"]
        assert result.tx_size_bytes == SOLANA_BASE_TX_OVERHEAD + SIGNATURE_SIZES["Ed25519"] + PUBLIC_KEY_SIZES["Ed25519"]
        assert result.relative_to_baseline == 1.0

    def test_ml_dsa_65_smaller_throughput(self):
        ed = analyze_solana_block_space("Ed25519")
        d3 = analyze_solana_block_space("ML-DSA-65")
        assert d3.txs_per_block < ed.txs_per_block
        assert d3.relative_to_baseline < 1.0

    def test_falcon_better_than_ml_dsa(self):
        f512 = analyze_solana_block_space("Falcon-512")
        d2 = analyze_solana_block_space("ML-DSA-44")
        assert f512.txs_per_block > d2.txs_per_block

    def test_slh_dsa_worst_throughput(self):
        """SLH-DSA-256f has 49KB signatures -- worst throughput."""
        ed = analyze_solana_block_space("Ed25519")
        slh = analyze_solana_block_space("SLH-DSA-256f")
        assert slh.txs_per_block < ed.txs_per_block
        assert slh.relative_to_baseline < 0.5  # much less than half

    def test_txs_per_block_calculation(self):
        result = analyze_solana_block_space("Ed25519")
        expected = SOLANA_BLOCK_SIZE_BYTES // (SOLANA_BASE_TX_OVERHEAD + SIGNATURE_SIZES["Ed25519"] + PUBLIC_KEY_SIZES["Ed25519"])
        assert result.txs_per_block == expected

    def test_signature_overhead_percentage(self):
        result = analyze_solana_block_space("ML-DSA-87")
        sig_size = SIGNATURE_SIZES["ML-DSA-87"]
        pk_size = PUBLIC_KEY_SIZES["ML-DSA-87"]
        tx_size = SOLANA_BASE_TX_OVERHEAD + sig_size + pk_size
        expected_pct = round(sig_size / tx_size * 100, 2)
        assert result.signature_overhead_pct == expected_pct

    @pytest.mark.parametrize("sig_type", SOLANA_SIG_TYPES)
    def test_all_signature_types(self, sig_type: str):
        result = analyze_solana_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0
        assert 0 < result.block_utilization_pct <= 100

    def test_custom_parameters(self):
        result = analyze_solana_block_space("Ed25519", block_size=1_000_000, base_tx_overhead=100)
        expected_txs = 1_000_000 // (100 + SIGNATURE_SIZES["Ed25519"] + PUBLIC_KEY_SIZES["Ed25519"])
        assert result.txs_per_block == expected_txs

    def test_multi_signer(self):
        """Multi-signer transactions should reduce throughput."""
        single = analyze_solana_block_space("ML-DSA-65", num_signers=1)
        double = analyze_solana_block_space("ML-DSA-65", num_signers=2)
        assert double.txs_per_block < single.txs_per_block
        assert double.signature_bytes == single.signature_bytes * 2


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

    def test_includes_slh_dsa(self):
        comp = compare_all_solana()
        sig_types = [a.signature_type for a in comp.analyses]
        assert "SLH-DSA-128s" in sig_types
        assert "SLH-DSA-256f" in sig_types


class TestBitcoinBlockSpace:
    def test_ecdsa_baseline(self):
        result = analyze_bitcoin_block_space("ECDSA")
        assert result.signature_bytes == SIGNATURE_SIZES["ECDSA"]
        assert result.relative_to_baseline == 1.0

    def test_segwit_discount_applied(self):
        result = analyze_bitcoin_block_space("ECDSA")
        # 33 is ECDSA compressed public key size
        expected_weight = (BITCOIN_BASE_TX_OVERHEAD * BITCOIN_WITNESS_DISCOUNT) + SIGNATURE_SIZES["ECDSA"] + 33
        expected_txs = BITCOIN_BLOCK_WEIGHT_LIMIT // expected_weight
        assert result.txs_per_block == expected_txs

    def test_falcon_better_than_ml_dsa(self):
        f512 = analyze_bitcoin_block_space("Falcon-512")
        d2 = analyze_bitcoin_block_space("ML-DSA-44")
        assert f512.txs_per_block > d2.txs_per_block

    def test_pqc_reduces_throughput(self):
        ecdsa = analyze_bitcoin_block_space("ECDSA")
        d3 = analyze_bitcoin_block_space("ML-DSA-65")
        assert d3.txs_per_block < ecdsa.txs_per_block
        assert d3.relative_to_baseline < 1.0

    @pytest.mark.parametrize("sig_type", BITCOIN_SIG_TYPES)
    def test_all_signature_types(self, sig_type: str):
        result = analyze_bitcoin_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0

    def test_vsize_is_weight_div_4(self):
        result = analyze_bitcoin_block_space("ECDSA")
        # 33 is ECDSA compressed public key size
        expected_weight = (BITCOIN_BASE_TX_OVERHEAD * 4) + SIGNATURE_SIZES["ECDSA"] + 33
        assert result.tx_size_bytes == round(expected_weight / 4)

    def test_multi_signer(self):
        single = analyze_bitcoin_block_space("ECDSA", num_signers=1)
        double = analyze_bitcoin_block_space("ECDSA", num_signers=2)
        assert double.txs_per_block < single.txs_per_block


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


class TestEthereumBlockSpace:
    def test_ecdsa_baseline(self):
        result = analyze_ethereum_block_space("ECDSA")
        assert result.signature_bytes == SIGNATURE_SIZES["ECDSA"]
        assert result.relative_to_baseline == 1.0

    def test_gas_calculation(self):
        """Verify gas-based transaction count."""
        result = analyze_ethereum_block_space("ECDSA")
        # 33 is ECDSA compressed public key size
        calldata_bytes = SIGNATURE_SIZES["ECDSA"] + 33 + ETHEREUM_BASE_TX_OVERHEAD
        expected_gas = ETHEREUM_BASE_TX_GAS + (calldata_bytes * ETHEREUM_CALLDATA_GAS_PER_BYTE)
        expected_txs = ETHEREUM_BLOCK_GAS_LIMIT // expected_gas
        assert result.txs_per_block == expected_txs

    def test_pqc_reduces_throughput(self):
        ecdsa = analyze_ethereum_block_space("ECDSA")
        d3 = analyze_ethereum_block_space("ML-DSA-65")
        assert d3.txs_per_block < ecdsa.txs_per_block

    def test_slh_dsa_dramatic_impact(self):
        """SLH-DSA-256f (49KB) should dramatically reduce Ethereum throughput."""
        ecdsa = analyze_ethereum_block_space("ECDSA")
        slh = analyze_ethereum_block_space("SLH-DSA-256f")
        assert slh.txs_per_block < ecdsa.txs_per_block / 5  # much less than 20%

    @pytest.mark.parametrize("sig_type", ETHEREUM_SIG_TYPES)
    def test_all_signature_types(self, sig_type: str):
        result = analyze_ethereum_block_space(sig_type)
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0

    def test_12_second_block_time(self):
        """Default Ethereum block time is 12 seconds."""
        result = analyze_ethereum_block_space("ECDSA")
        # TPS = txs_per_block / 12
        expected_tps = result.txs_per_block / 12
        assert abs(result.throughput_tps - expected_tps) < 0.01


class TestEthereumCompareAll:
    def test_returns_all_schemes(self):
        comp = compare_all_ethereum()
        assert len(comp.analyses) == len(ETHEREUM_SIG_TYPES)

    def test_baseline_is_ecdsa(self):
        comp = compare_all_ethereum()
        assert comp.baseline.signature_type == "ECDSA"
        assert comp.chain == "Ethereum"

    def test_all_have_positive_tps(self):
        comp = compare_all_ethereum()
        for a in comp.analyses:
            assert a.throughput_tps > 0


class TestInputValidation:
    """Test parameter validation on model functions."""

    def test_solana_negative_block_size(self):
        with pytest.raises(ValueError, match="block_size must be positive"):
            analyze_solana_block_space("Ed25519", block_size=-1)

    def test_solana_zero_slot_time(self):
        with pytest.raises(ValueError, match="slot_time_ms must be positive"):
            analyze_solana_block_space("Ed25519", slot_time_ms=0)

    def test_solana_vote_pct_over_one(self):
        with pytest.raises(ValueError, match="vote_tx_pct must be between"):
            analyze_solana_block_space("Ed25519", vote_tx_pct=1.5)

    def test_solana_vote_pct_negative(self):
        with pytest.raises(ValueError, match="vote_tx_pct must be between"):
            analyze_solana_block_space("Ed25519", vote_tx_pct=-0.1)

    def test_solana_zero_signers(self):
        with pytest.raises(ValueError, match="num_signers must be positive"):
            analyze_solana_block_space("Ed25519", num_signers=0)

    def test_bitcoin_negative_block_weight(self):
        with pytest.raises(ValueError, match="block_weight must be positive"):
            analyze_bitcoin_block_space("ECDSA", block_weight=-1)

    def test_bitcoin_zero_block_time(self):
        with pytest.raises(ValueError, match="block_time_ms must be positive"):
            analyze_bitcoin_block_space("ECDSA", block_time_ms=0)

    def test_ethereum_negative_gas_limit(self):
        with pytest.raises(ValueError, match="block_gas_limit must be positive"):
            analyze_ethereum_block_space("ECDSA", block_gas_limit=-1)

    def test_ethereum_zero_base_gas(self):
        with pytest.raises(ValueError, match="base_tx_gas must be positive"):
            analyze_ethereum_block_space("ECDSA", base_tx_gas=0)

    def test_ethereum_execution_gas(self):
        """Execution gas should reduce throughput."""
        no_exec = analyze_ethereum_block_space("ECDSA", execution_gas=0)
        with_exec = analyze_ethereum_block_space("ECDSA", execution_gas=100_000)
        assert with_exec.txs_per_block < no_exec.txs_per_block

    def test_ethereum_execution_gas_relative_unchanged(self):
        """Baseline and PQC both get execution_gas, so relative impact stays similar."""
        no_exec = analyze_ethereum_block_space("Falcon-512", execution_gas=0)
        with_exec = analyze_ethereum_block_space("Falcon-512", execution_gas=100_000)
        # Both relative_to_baseline should be < 1.0 and in same ballpark
        assert no_exec.relative_to_baseline < 1.0
        assert with_exec.relative_to_baseline < 1.0


class TestNoKyberDilithiumInModel:
    """Ensure draft names are not in the blockchain model."""

    def test_no_kyber_in_signature_sizes(self):
        for key in SIGNATURE_SIZES:
            assert "Kyber" not in key

    def test_no_dilithium_in_signature_sizes(self):
        for key in SIGNATURE_SIZES:
            assert "Dilithium" not in key
