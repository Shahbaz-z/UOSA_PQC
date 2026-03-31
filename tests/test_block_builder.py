"""Tests for simulator/economics/block_builder.py.

Covers Transaction scoring, BlockBuilder.build_block(), algo_inclusion_bias(),
and censorship_threshold().
"""

import pytest
from simulator.economics.block_builder import (
    Transaction,
    BlockBuilder,
    VERIFY_TIME_US,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


def make_tx(
    tx_id: str,
    algo: str,
    fee: float,
    chain: str = "ethereum",
) -> Transaction:
    """Helper: build a Transaction for a given algorithm and fee."""
    sig_sz = SIGNATURE_SIZES.get(algo, 64)
    pk_sz  = PUBLIC_KEY_SIZES.get(algo, 32)
    tx_sz  = 120 + sig_sz + pk_sz

    from simulator.chains.ethereum_specific import PQC_VERIFICATION_GAS
    from simulator.chains.solana_specific import CU_COSTS

    gas = PQC_VERIFICATION_GAS.get(algo, 3_000) if chain == "ethereum" else 0
    cu  = CU_COSTS.get(algo, 8_000) if chain == "solana" else 0
    wt  = tx_sz * 4 if chain == "bitcoin" else 0

    return Transaction(
        tx_id         = tx_id,
        sig_algorithm = algo,
        fee           = fee,
        size_bytes    = tx_sz,
        gas_used      = gas,
        compute_units = cu,
        weight_units  = wt,
    )


class TestTransactionScoring:
    def test_fee_per_byte_positive(self):
        tx = make_tx("t1", "ECDSA", fee=1000.0)
        assert tx.fee_per_byte() > 0

    def test_fee_per_gas_positive(self):
        tx = make_tx("t1", "ECDSA", fee=1000.0, chain="ethereum")
        assert tx.fee_per_gas() > 0

    def test_verify_time_set_from_table(self):
        tx = make_tx("t1", "ECDSA", fee=100.0)
        assert tx.verify_time_us == VERIFY_TIME_US.get("ECDSA", 60.0)

    def test_slh_dsa_has_long_verify_time(self):
        tx_slh  = make_tx("t2", "SLH-DSA-128s", fee=100.0)
        tx_ecdsa = make_tx("t3", "ECDSA", fee=100.0)
        assert tx_slh.verify_time_us > tx_ecdsa.verify_time_us

    def test_fee_per_verify_us_falcon_higher_than_slh(self):
        # At same fee, Falcon has higher fee/CU (faster verify)
        tx_f  = make_tx("f", "Falcon-512", fee=100.0)
        tx_s  = make_tx("s", "SLH-DSA-128s", fee=100.0)
        assert tx_f.fee_per_verify_us() > tx_s.fee_per_verify_us()


class TestBlockBuilder:
    def test_build_block_returns_list(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        mempool = [make_tx(f"t{i}", "ECDSA", fee=float(100 - i)) for i in range(10)]
        included = builder.build_block(mempool, block_limit={"gas": 300_000_000})
        assert isinstance(included, list)

    def test_build_block_orders_by_priority(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        # Create txs with different fees; higher fee → higher priority
        mempool = [
            make_tx("low",  "ECDSA", fee=10.0,  chain="ethereum"),
            make_tx("high", "ECDSA", fee=1000.0, chain="ethereum"),
            make_tx("mid",  "ECDSA", fee=100.0,  chain="ethereum"),
        ]
        included = builder.build_block(mempool, block_limit={"gas": 300_000_000})
        tx_ids = [tx.tx_id for tx in included]
        # All three should fit with generous limit
        assert "high" in tx_ids
        assert "low" in tx_ids

    def test_build_block_respects_gas_limit(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        # In the test make_tx helper, gas_used = PQC_VERIFICATION_GAS[algo] (=3,000 for ECDSA).
        # Set limit so only 2 txs fit: 3,000 × 2 = 6,000 gas.
        mempool = [make_tx(f"t{i}", "ECDSA", fee=float(100 + i)) for i in range(20)]
        included = builder.build_block(mempool, block_limit={"gas": 6_000})
        assert len(included) <= 2

    def test_bitcoin_scoring_uses_weight_units(self):
        builder = BlockBuilder(chain="bitcoin", sig_preference_model="fee_per_weight_unit")
        mempool = [make_tx(f"t{i}", "ECDSA", fee=float(1000 - i * 10), chain="bitcoin") for i in range(5)]
        # Should run without error
        included = builder.build_block(mempool, block_limit={"weight_units": 4_000_000})
        assert len(included) > 0


class TestAlgoInclusionBias:
    def test_returns_all_algos(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        algos   = ["ECDSA", "ML-DSA-65", "Falcon-512"]
        mempool = []
        for algo in algos:
            for j in range(5):
                mempool.append(make_tx(f"{algo}_{j}", algo, fee=100.0, chain="ethereum"))

        rates = builder.algo_inclusion_bias(mempool, block_limit={"gas": 300_000_000})
        for algo in algos:
            assert algo in rates

    def test_rates_are_fractions(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        algos   = ["ECDSA", "ML-DSA-65"]
        mempool = []
        for algo in algos:
            for j in range(10):
                mempool.append(make_tx(f"{algo}_{j}", algo, fee=100.0, chain="ethereum"))

        rates = builder.algo_inclusion_bias(mempool, block_limit={"gas": 300_000_000})
        for rate in rates.values():
            assert 0.0 <= rate <= 1.0


class TestCensorshipThreshold:
    def test_classical_baseline_is_one(self):
        builder = BlockBuilder(
            chain                = "ethereum",
            sig_preference_model = "fee_per_gas",
            classical_algo       = "ECDSA",
        )
        thresholds = builder.censorship_threshold(
            algorithms=["ECDSA"], baseline_fee=1.0
        )
        assert thresholds["ECDSA"] == pytest.approx(1.0, rel=0.05)

    def test_slh_dsa_requires_highest_premium(self):
        builder = BlockBuilder(
            chain                = "ethereum",
            sig_preference_model = "fee_per_gas",
            classical_algo       = "ECDSA",
        )
        thresholds = builder.censorship_threshold(
            algorithms=["ML-DSA-65", "Falcon-512", "SLH-DSA-128s"],
            baseline_fee=1.0,
        )
        # SLH-DSA-128s has very high gas → needs highest premium
        assert thresholds["SLH-DSA-128s"] > thresholds["ML-DSA-65"]
        assert thresholds["SLH-DSA-128s"] > thresholds["Falcon-512"]

    def test_all_thresholds_positive(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        thresholds = builder.censorship_threshold(
            algorithms=["ML-DSA-65", "Falcon-512"],
            baseline_fee=1.0,
        )
        for algo, mult in thresholds.items():
            assert mult > 0, f"Threshold for {algo} is not positive"

    def test_inclusion_rate_comparison_returns_dict(self):
        builder = BlockBuilder(chain="ethereum", sig_preference_model="fee_per_gas")
        result = builder.inclusion_rate_comparison(
            algorithms=["ECDSA", "ML-DSA-65"],
            pool_size_per_algo=20,
        )
        for algo in ["ECDSA", "ML-DSA-65"]:
            assert algo in result
            assert "inclusion_rate" in result[algo]
            assert "fee_premium_needed" in result[algo]
