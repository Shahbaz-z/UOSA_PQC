"""Tests for chain-specific BTC/ETH transaction models."""

import pytest
from simulator.chains.bitcoin_specific import BitcoinTxModel, DEFAULT_BITCOIN_TX_MODEL
from simulator.chains.ethereum_specific import EthereumTxModel, DEFAULT_ETHEREUM_TX_MODEL


class TestBitcoinTxModel:
    """Test Bitcoin UTXO + SegWit weight model."""

    def test_default_instance(self):
        m = DEFAULT_BITCOIN_TX_MODEL
        assert m.avg_inputs == 2
        assert m.avg_outputs == 2
        assert m.witness_discount == 0.25

    def test_base_size_no_witness(self):
        """Base size excludes signatures (they're in witness)."""
        m = BitcoinTxModel(avg_inputs=1, avg_outputs=1)
        base = m.base_size(sig_size=64, pk_size=32)
        # Should not depend on sig/pk size (they go in witness)
        base2 = m.base_size(sig_size=2000, pk_size=1000)
        assert base == base2

    def test_witness_size_scales_with_signature(self):
        """Larger signatures → larger witness data."""
        m = BitcoinTxModel(avg_inputs=2, avg_outputs=2)
        w_ecdsa = m.witness_size(sig_size=72, pk_size=33)
        w_mldsa = m.witness_size(sig_size=3293, pk_size=1952)
        assert w_mldsa > w_ecdsa * 10  # ML-DSA is much bigger

    def test_weight_segwit_discount(self):
        """SegWit gives witness data 75% discount on weight."""
        m = BitcoinTxModel(avg_inputs=1, avg_outputs=1)
        base = m.base_size(72, 33)
        witness = m.witness_size(72, 33)
        weight = m.tx_weight(72, 33)
        # weight = base * 4 + witness * 1
        assert weight == base * 4 + witness

    def test_weight_discount_helps_pqc(self):
        """PQC sigs in witness get discounted, limiting weight inflation."""
        m = DEFAULT_BITCOIN_TX_MODEL
        # ECDSA: 72-byte sig, 33-byte pk
        w_ecdsa = m.tx_weight(72, 33)
        # ML-DSA-65: 3293-byte sig, 1952-byte pk
        w_mldsa = m.tx_weight(3293, 1952)
        # Without discount: ~50x heavier. With discount: much less.
        ratio = w_mldsa / w_ecdsa
        assert ratio < 20  # Discount keeps it manageable

    def test_tx_bytes_no_discount(self):
        """Propagation bytes have no discount."""
        m = DEFAULT_BITCOIN_TX_MODEL
        bytes_ecdsa = m.tx_bytes(72, 33)
        bytes_mldsa = m.tx_bytes(3293, 1952)
        # Raw bytes ratio should be much higher than weight ratio
        byte_ratio = bytes_mldsa / bytes_ecdsa
        weight_ratio = m.tx_weight(3293, 1952) / m.tx_weight(72, 33)
        assert byte_ratio > weight_ratio

    def test_txs_per_block(self):
        """Block filling with ECDSA should give many txs."""
        m = DEFAULT_BITCOIN_TX_MODEL
        n = m.txs_per_block(72, 33, block_weight_limit=4_000_000)
        assert n > 1000  # Should fit many ECDSA txs

    def test_txs_per_block_pqc_fewer(self):
        """PQC signatures fit fewer txs per block."""
        m = DEFAULT_BITCOIN_TX_MODEL
        n_ecdsa = m.txs_per_block(72, 33)
        n_pqc = m.txs_per_block(3293, 1952)
        assert n_pqc < n_ecdsa

    def test_zero_sig_size(self):
        """Edge case: zero signature size."""
        m = DEFAULT_BITCOIN_TX_MODEL
        w = m.tx_weight(0, 0)
        assert w > 0  # Still has base data


class TestEthereumTxModel:
    """Test Ethereum gas metering model."""

    def test_default_instance(self):
        m = DEFAULT_ETHEREUM_TX_MODEL
        assert m.base_gas == 21_000
        assert m.base_tx_bytes == 120

    def test_gas_includes_base(self):
        """Gas always includes 21,000 base."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        gas = m.tx_gas(64, 32)
        assert gas >= 21_000

    def test_gas_scales_with_sig_size(self):
        """Larger sigs → more calldata gas."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        gas_ecdsa = m.tx_gas(65, 33)
        gas_mldsa = m.tx_gas(3293, 1952)
        assert gas_mldsa > gas_ecdsa

    def test_tx_bytes_independent_of_gas(self):
        """Propagation bytes ≠ gas."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        gas = m.tx_gas(65, 33)
        bytes_ = m.tx_bytes(65, 33)
        assert gas != bytes_  # Very different units

    def test_tx_bytes_base(self):
        """Base bytes should be 120 + sig + pk + calldata."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        b = m.tx_bytes(65, 33)
        assert b == 120 + 65 + 33 + 100  # base + sig + pk + avg_calldata

    def test_txs_per_block(self):
        """30M gas limit should fit many ECDSA txs."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        n = m.txs_per_block(65, 33)
        assert n > 500

    def test_pqc_fewer_txs(self):
        """PQC txs consume more gas, fewer fit per block."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        n_ecdsa = m.txs_per_block(65, 33)
        n_pqc = m.txs_per_block(3293, 1952)
        assert n_pqc < n_ecdsa

    def test_block_bytes(self):
        """Block byte size estimate should be positive."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        bb = m.block_bytes(65, 33)
        assert bb > 0

    def test_calldata_gas_zero_bytes(self):
        """Zero bytes cost less gas."""
        m = DEFAULT_ETHEREUM_TX_MODEL
        # All non-zero
        g1 = m.calldata_gas(100)
        # Expect: 95 * 16 + 5 * 4 = 1540 (with 5% zero fraction)
        assert g1 > 0
