"""Tests for the PQC-aware Ethereum gas schedule.

Covers PQC_VERIFICATION_GAS table, EthereumTxModel.tx_gas(),
dual_sig_gas(), and gas overhead ratios.
"""

import pytest
from simulator.chains.ethereum_specific import (
    PQC_VERIFICATION_GAS,
    EthereumTxModel,
    GAS_PER_CYCLE,
    estimate_pqc_gas,
    DEFAULT_ETHEREUM_TX_MODEL,
    AA_USEROPERATION_OVERHEAD_GAS,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


class TestPQCVerificationGasTable:
    def test_ecdsa_is_3000(self):
        assert PQC_VERIFICATION_GAS["ECDSA"] == 3_000

    def test_ed25519_is_3000(self):
        assert PQC_VERIFICATION_GAS["Ed25519"] == 3_000

    def test_mldsa65_more_expensive_than_ecdsa(self):
        assert PQC_VERIFICATION_GAS["ML-DSA-65"] > PQC_VERIFICATION_GAS["ECDSA"]

    def test_falcon512_cheaper_than_mldsa65(self):
        # Falcon has faster verify than ML-DSA
        assert PQC_VERIFICATION_GAS["Falcon-512"] < PQC_VERIFICATION_GAS["ML-DSA-65"]

    def test_slh_dsa_128s_most_expensive(self):
        # SLH-DSA-128s has very slow verify
        assert PQC_VERIFICATION_GAS["SLH-DSA-128s"] > PQC_VERIFICATION_GAS["ML-DSA-87"]
        assert PQC_VERIFICATION_GAS["SLH-DSA-128s"] > PQC_VERIFICATION_GAS["Falcon-1024"]

    def test_hybrid_is_sum_of_classical_and_pqc(self):
        # hybrid_MLDSA65_ECDSA should be ~ECDSA + ML-DSA-65
        hybrid = PQC_VERIFICATION_GAS["hybrid_MLDSA65_ECDSA"]
        expected = PQC_VERIFICATION_GAS["ECDSA"] + PQC_VERIFICATION_GAS["ML-DSA-65"]
        assert hybrid == pytest.approx(expected, abs=1000)

    def test_all_values_positive(self):
        for algo, gas in PQC_VERIFICATION_GAS.items():
            assert gas > 0, f"{algo} has non-positive gas"

    def test_all_values_are_integers(self):
        for algo, gas in PQC_VERIFICATION_GAS.items():
            assert isinstance(gas, int), f"{algo} gas is not int"


class TestEstimatePqcGas:
    def test_positive_cycles_returns_positive_gas(self):
        assert estimate_pqc_gas(50_000) > 0

    def test_calibration_ecdsa(self):
        # ~50,000 cycles × 0.06 ≈ 3,000 gas
        gas = estimate_pqc_gas(50_000)
        assert abs(gas - 3_000) < 500


class TestEthereumTxModelPQCAware:
    def test_default_model_backward_compatible(self):
        model = DEFAULT_ETHEREUM_TX_MODEL
        assert model.sig_algorithm == "ECDSA"
        sig, pk = SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"]
        gas = model.tx_gas(sig, pk)
        # Should match the old hardcoded sig_verification_gas=3000 behaviour
        assert gas > 21_000

    def test_sig_verification_gas_property(self):
        model = EthereumTxModel(sig_algorithm="ML-DSA-65")
        assert model.sig_verification_gas == PQC_VERIFICATION_GAS["ML-DSA-65"]

    def test_unknown_algo_falls_back_to_3000(self):
        model = EthereumTxModel(sig_algorithm="UNKNOWN_ALGO")
        assert model.sig_verification_gas == 3_000

    def test_pqc_gas_greater_than_classical(self):
        model = EthereumTxModel(sig_algorithm="ML-DSA-65")
        sig, pk = SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"]
        pqc_gas = model.tx_gas(sig, pk)
        classical_model = EthereumTxModel(sig_algorithm="ECDSA")
        classical_gas = classical_model.tx_gas(
            SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"]
        )
        assert pqc_gas > classical_gas

    def test_txs_per_block_decreases_with_pqc(self):
        classical = EthereumTxModel(sig_algorithm="ECDSA")
        pqc       = EthereumTxModel(sig_algorithm="ML-DSA-65")
        classical_txs = classical.txs_per_block(
            SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"]
        )
        pqc_txs = pqc.txs_per_block(
            SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"]
        )
        assert pqc_txs < classical_txs

    def test_algo_override_in_tx_gas(self):
        model = EthereumTxModel(sig_algorithm="ECDSA")
        sig, pk = SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"]
        # Override to ML-DSA-65 via parameter
        gas_override = model.tx_gas(sig, pk, sig_algorithm="ML-DSA-65")
        # Using default ECDSA
        gas_default  = model.tx_gas(sig, pk)
        assert gas_override != gas_default

    def test_gas_overhead_ratio_classical_is_one(self):
        model = EthereumTxModel(sig_algorithm="ECDSA")
        ratio = model.gas_overhead_ratio(
            SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"], sig_algorithm="ECDSA"
        )
        assert ratio == pytest.approx(1.0, rel=0.01)

    def test_gas_overhead_ratio_pqc_greater_than_one(self):
        model = EthereumTxModel(sig_algorithm="ML-DSA-65")
        ratio = model.gas_overhead_ratio(
            SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"],
            sig_algorithm="ML-DSA-65"
        )
        assert ratio > 1.0


class TestDualSigGas:
    def test_dual_sig_greater_than_either_alone(self):
        model = EthereumTxModel()
        ecdsa_sig, ecdsa_pk = SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"]
        pqc_sig, pqc_pk     = SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"]

        dual = model.dual_sig_gas("ECDSA", "ML-DSA-65",
                                  ecdsa_sig, ecdsa_pk, pqc_sig, pqc_pk)
        ecdsa_only = model.tx_gas(ecdsa_sig, ecdsa_pk, sig_algorithm="ECDSA")
        pqc_only   = model.tx_gas(pqc_sig, pqc_pk, sig_algorithm="ML-DSA-65")

        assert dual > ecdsa_only
        assert dual > pqc_only

    def test_dual_sig_approximately_sum_of_parts(self):
        model = EthereumTxModel()
        ecdsa_sig, ecdsa_pk = SIGNATURE_SIZES["ECDSA"], PUBLIC_KEY_SIZES["ECDSA"]
        falcon_sig, falcon_pk = SIGNATURE_SIZES["Falcon-512"], PUBLIC_KEY_SIZES["Falcon-512"]

        dual = model.dual_sig_gas("ECDSA", "Falcon-512",
                                  ecdsa_sig, ecdsa_pk, falcon_sig, falcon_pk)
        # Dual gas includes both verify costs; should be at least the sum
        assert dual > (
            PQC_VERIFICATION_GAS["ECDSA"] + PQC_VERIFICATION_GAS["Falcon-512"]
        )


class TestAAOverhead:
    def test_aa_overhead_additive(self):
        model_no_aa = EthereumTxModel(
            sig_algorithm="ML-DSA-65",
            account_abstraction_overhead_gas=0,
        )
        model_aa = EthereumTxModel(
            sig_algorithm="ML-DSA-65",
            account_abstraction_overhead_gas=AA_USEROPERATION_OVERHEAD_GAS,
        )
        sig, pk = SIGNATURE_SIZES["ML-DSA-65"], PUBLIC_KEY_SIZES["ML-DSA-65"]
        diff = model_aa.tx_gas(sig, pk) - model_no_aa.tx_gas(sig, pk)
        assert diff == AA_USEROPERATION_OVERHEAD_GAS
