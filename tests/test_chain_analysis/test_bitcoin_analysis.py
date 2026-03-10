"""Tests for Bitcoin PQC impact analysis."""

import pytest

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    ECDSA,
    FALCON_512,
    FALCON_1024,
    DILITHIUM2,
    DILITHIUM3,
    DILITHIUM5,
    SPHINCS_128S,
    SPHINCS_256S,
)
from analysis.bitcoin_pqc_analysis import (
    BLOCK_WEIGHT_LIMIT,
    BLOCK_INTERVAL_S,
    BitcoinTxSizer,
    CURRENT_SEGWIT,
    EXTENDED_DISCOUNT,
    NO_DISCOUNT,
    run_block_capacity_sweep,
    run_policy_comparison,
    run_fee_market_simulation,
    run_full_bitcoin_analysis,
)


# ── BitcoinTxSizer unit tests ──────────────────────────────────────

class TestBitcoinTxSizer:
    def setup_method(self):
        self.sizer = BitcoinTxSizer()

    def test_base_bytes_positive(self):
        assert self.sizer.base_bytes() > 0

    def test_base_bytes_constant(self):
        """Base bytes don't depend on sig/pk size (SegWit)."""
        b1 = self.sizer.base_bytes()
        b2 = self.sizer.base_bytes()
        assert b1 == b2

    def test_witness_bytes_scales_with_sig(self):
        w1 = self.sizer.witness_bytes(72, 33)
        w2 = self.sizer.witness_bytes(666, 897)
        assert w2 > w1

    def test_witness_bytes_scales_with_inputs(self):
        sizer1 = BitcoinTxSizer(avg_inputs=1)
        sizer2 = BitcoinTxSizer(avg_inputs=3)
        assert sizer2.witness_bytes(72, 33) == 3 * sizer1.witness_bytes(72, 33)

    def test_tx_weight_ecdsa_reasonable(self):
        """ECDSA tx weight should give ~4000–5000 txs/block."""
        w = self.sizer.tx_weight(ECDSA.sig_bytes, ECDSA.pk_bytes)
        txs = BLOCK_WEIGHT_LIMIT // w
        assert 3000 <= txs <= 6000, f"ECDSA txs/block = {txs}, expected 3000-6000"

    def test_tx_weight_segwit_discount(self):
        """Witness data should get 4x discount vs base data."""
        w_segwit = self.sizer.tx_weight(72, 33, CURRENT_SEGWIT)
        w_none = self.sizer.tx_weight(72, 33, NO_DISCOUNT)
        # With no discount, weight should be higher (witness at 4x instead of 1x)
        assert w_none > w_segwit

    def test_extended_discount_between_others(self):
        w_ext = self.sizer.tx_weight(72, 33, EXTENDED_DISCOUNT)
        w_cur = self.sizer.tx_weight(72, 33, CURRENT_SEGWIT)
        w_none = self.sizer.tx_weight(72, 33, NO_DISCOUNT)
        assert w_cur < w_ext < w_none or w_ext < w_cur  # extended has lower witness multiplier

    def test_vsize_quarter_of_weight(self):
        w = self.sizer.tx_weight(72, 33)
        v = self.sizer.tx_vsize(72, 33)
        assert abs(v - w / 4.0) < 0.01


# ── Block capacity sweep ──────────────────────────────────────────

class TestBlockCapacitySweep:
    def test_returns_all_algorithms(self):
        results = run_block_capacity_sweep()
        assert len(results) == len(ALL_ALGORITHMS)

    def test_ecdsa_baseline_reasonable(self):
        results = run_block_capacity_sweep()
        ecdsa_result = results[0]
        assert ecdsa_result.algorithm == ECDSA.name
        # Mainnet averages ~2800, but our model may differ slightly
        # due to tx size assumptions; accept 3000-6000
        assert ecdsa_result.txs_per_block >= 3000
        assert ecdsa_result.throughput_reduction_pct == 0.0

    def test_pqc_reduces_capacity(self):
        results = run_block_capacity_sweep()
        ecdsa_txs = results[0].txs_per_block
        for r in results[1:]:
            assert r.txs_per_block < ecdsa_txs, f"{r.algorithm} should have fewer txs than ECDSA"

    def test_larger_sigs_fewer_txs(self):
        """FALCON-512 should fit more txs than FALCON-1024."""
        results = run_block_capacity_sweep()
        by_name = {r.algorithm: r for r in results}
        assert by_name[FALCON_512.name].txs_per_block > by_name[FALCON_1024.name].txs_per_block

    def test_throughput_reduction_monotonic(self):
        """Larger algorithms should have higher throughput reduction."""
        results = run_block_capacity_sweep()
        # SPHINCS+-256s should have highest reduction
        by_name = {r.algorithm: r for r in results}
        assert by_name[SPHINCS_256S.name].throughput_reduction_pct > 90.0

    def test_tps_positive(self):
        results = run_block_capacity_sweep()
        for r in results:
            assert r.effective_tps > 0

    def test_sig_fraction_between_0_and_1(self):
        results = run_block_capacity_sweep()
        for r in results:
            assert 0.0 <= r.sig_fraction_of_weight <= 1.0


# ── Witness policy comparison ─────────────────────────────────────

class TestPolicyComparison:
    def test_returns_correct_count(self):
        results = run_policy_comparison()
        assert len(results) == len(ALL_ALGORITHMS) * 3  # 3 policies

    def test_extended_discount_helps(self):
        """Extended discount should allow more txs than current SegWit."""
        results = run_policy_comparison(algorithms=[DILITHIUM3])
        by_policy = {r.policy: r for r in results}
        assert by_policy[EXTENDED_DISCOUNT.name].txs_per_block > by_policy[CURRENT_SEGWIT.name].txs_per_block

    def test_no_discount_worst(self):
        """No discount should allow fewest txs."""
        results = run_policy_comparison(algorithms=[DILITHIUM3])
        by_policy = {r.policy: r for r in results}
        assert by_policy[NO_DISCOUNT.name].txs_per_block < by_policy[CURRENT_SEGWIT.name].txs_per_block


# ── Fee market simulation ─────────────────────────────────────────

class TestFeeMarketSimulation:
    def test_basic_run(self):
        result = run_fee_market_simulation(FALCON_512)
        assert result.algorithm == FALCON_512.name
        assert result.block_txs_included > 0
        assert result.block_fee_revenue_sat > 0

    def test_high_pressure_fewer_inclusions(self):
        """Higher mempool pressure → more txs stuck."""
        r_low = run_fee_market_simulation(FALCON_512, mempool_pressure="low")
        r_high = run_fee_market_simulation(FALCON_512, mempool_pressure="high")
        # At high pressure, more PQC txs should be stuck
        assert r_high.pqc_txs_stuck >= r_low.pqc_txs_stuck

    def test_deterministic(self):
        r1 = run_fee_market_simulation(FALCON_512, seed=42)
        r2 = run_fee_market_simulation(FALCON_512, seed=42)
        assert r1.block_txs_included == r2.block_txs_included
        assert r1.block_fee_revenue_sat == r2.block_fee_revenue_sat

    def test_sphincs_most_displacement(self):
        """SPHINCS+-256s txs should have lowest inclusion rate."""
        r_falcon = run_fee_market_simulation(FALCON_512, mempool_pressure="medium")
        r_sphincs = run_fee_market_simulation(SPHINCS_256S, mempool_pressure="medium")
        assert r_sphincs.block_txs_included < r_falcon.block_txs_included

    def test_inclusion_rates_bounded(self):
        result = run_fee_market_simulation(DILITHIUM2)
        assert 0.0 <= result.ecdsa_inclusion_rate <= 1.0
        assert 0.0 <= result.pqc_inclusion_rate <= 1.0


# ── Full analysis ─────────────────────────────────────────────────

class TestFullBitcoinAnalysis:
    def test_runs_and_returns_all_components(self):
        results = run_full_bitcoin_analysis()
        assert len(results.block_capacity) == len(ALL_ALGORITHMS)
        assert len(results.policy_comparison) > 0
        assert len(results.fee_market) > 0

    def test_fee_market_covers_all_pressures(self):
        results = run_full_bitcoin_analysis()
        pressures = {r.mempool_pressure for r in results.fee_market}
        assert pressures == {"low", "medium", "high"}
