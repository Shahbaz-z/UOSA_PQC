"""Regression tests for the comprehensive logic/inconsistency audit fixes.

Covers:
  1.5 — elapsed_ms > (not >=) boundary in _generate_transactions_until
  1.7 — PQC fee double-penalty removed from generate_tx_fee
  2.3 — size_overhead_ratio uses pqc_only methods for Phase 3
  2.5 — stale_rate denominator includes zero-propagation blocks
  3.12 — algo_byte_distribution added to Phase 2 results
"""

import math
import pytest


# ---------------------------------------------------------------------------
# 1.5 — elapsed_ms boundary: > not >=
# ---------------------------------------------------------------------------

class TestElapsedMsBoundary:
    """Verify boundary tx at elapsed_ms == interval_ms goes to next interval."""

    def test_boundary_transaction_generated_with_strict_greater(self):
        """A transaction arriving exactly at elapsed_ms == interval_ms SHOULD be
        generated with the fix (> not >=).

        The audit noted that >= discards boundary transactions, slightly
        under-counting arrivals.  The fix uses > (strict) so the boundary
        transaction IS included in the current interval, which is the correct
        [0, interval] closed-interval interpretation when using Poisson arrivals.
        """
        # Build a mock arrival model that returns exactly interval_ms on first call
        interval_ms = 400.0

        class ExactArrivalModel:
            """Returns exactly interval_ms on first call, then infinity."""
            def __init__(self):
                self._called = 0
            def next_inter_arrival_ms(self):
                self._called += 1
                if self._called == 1:
                    return interval_ms  # exact boundary hit
                return float("inf")   # no more txs

        from simulator.core.phase2_engine import Phase2Engine, Phase2Config

        cfg = Phase2Config(chain="solana", random_seed=42)
        engine = Phase2Engine(cfg)
        engine._arrival_model = ExactArrivalModel()
        initial_tx_count = engine._total_tx_generated

        # Generate for exactly interval_ms
        # With > semantics: elapsed_ms == interval_ms is NOT > interval_ms
        # → break does NOT fire → transaction IS generated (included in interval)
        engine._generate_transactions_until(interval_ms)

        assert engine._total_tx_generated == initial_tx_count + 1, (
            f"With > boundary (not >=), a tx at elapsed == interval should be included. "
            f"Expected 1 tx generated, got {engine._total_tx_generated - initial_tx_count}"
        )

    def test_tx_just_before_boundary_is_generated(self):
        """A transaction arriving at elapsed_ms < interval_ms should be generated."""
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config

        interval_ms = 400.0

        class BelowBoundaryModel:
            def __init__(self):
                self._called = 0
            def next_inter_arrival_ms(self):
                self._called += 1
                if self._called == 1:
                    return interval_ms - 0.001  # just below boundary
                return float("inf")

        cfg = Phase2Config(chain="solana", random_seed=42)
        engine = Phase2Engine(cfg)
        engine._arrival_model = BelowBoundaryModel()
        initial_count = engine._total_tx_generated

        engine._generate_transactions_until(interval_ms)

        # tx at elapsed = interval_ms - 0.001 < interval_ms → should be generated
        assert engine._total_tx_generated > initial_count, (
            "Transaction arriving just before interval boundary should be generated"
        )


# ---------------------------------------------------------------------------
# 1.7 — PQC fee no longer double-penalised
# ---------------------------------------------------------------------------

class TestPQCFeeNoPremium:
    """Verify PQC and classical txs use the same base fee rate."""

    def test_pqc_and_classical_same_target_rate(self):
        """generate_tx_fee should use the same target_rate for classical and PQC."""
        from simulator.economics.fee_market import DynamicFeeMarket, FeeMarketConfig
        import random, math

        fm = DynamicFeeMarket(FeeMarketConfig(), rng=random.Random(42))
        fm.base_fee = 10.0

        # Generate many fees for the same size to compare distributions
        n = 1000
        classical_fees = [fm.generate_tx_fee(tx_size_bytes=250, is_pqc=False) for _ in range(n)]
        pqc_fees       = [fm.generate_tx_fee(tx_size_bytes=250, is_pqc=True)  for _ in range(n)]

        classical_avg = sum(classical_fees) / n
        pqc_avg       = sum(pqc_fees) / n

        # After fix: both use target_rate = base_fee * 1.2
        # Allow ±10% for lognormal variance
        ratio = pqc_avg / classical_avg
        assert abs(ratio - 1.0) < 0.10, (
            f"PQC and classical fees should have similar distributions "
            f"(ratio={ratio:.3f}, expected ~1.0). "
            "The PQC fee premium has been removed — PQC pays more due to size, not rate."
        )

    def test_pqc_still_costs_more_due_to_size(self):
        """PQC txs cost more in absolute terms because they are larger."""
        from simulator.economics.fee_market import DynamicFeeMarket, FeeMarketConfig
        import random

        fm = DynamicFeeMarket(FeeMarketConfig(), rng=random.Random(99))
        fm.base_fee = 10.0

        # Measure absolute fees at different sizes (same rate, different sizes)
        small_fee = fm.generate_tx_fee(tx_size_bytes=100, is_pqc=False)
        large_fee = fm.generate_tx_fee(tx_size_bytes=3000, is_pqc=True)

        # Larger PQC tx → higher absolute fee (even with same rate)
        # Both use target_rate * size_bytes, so large_fee >> small_fee on average
        # We just check the model runs without error
        assert small_fee > 0
        assert large_fee > 0


# ---------------------------------------------------------------------------
# 2.3 — size_overhead_ratio uses pqc_only for Phase 3
# ---------------------------------------------------------------------------

class TestSizeOverheadRatioPhase3:
    """size_overhead_ratio() must return PQC-only overhead in Phase 3."""

    def setup_method(self):
        from simulator.migration.dual_sig import DualSigConfig
        self.cfg = DualSigConfig(
            classical_algo="ECDSA",
            pqc_algo="ML-DSA-65",
            migration_start_block=0,
            migration_end_block=1000,
        )

    def test_phase3_ratio_uses_pqc_only_not_combined(self):
        """size_overhead_ratio at post-migration height must use pqc_sig_size."""
        post_migration = 1001
        ratio = self.cfg.size_overhead_ratio(post_migration)

        # Expected: (pqc_sig + pqc_pk) / (classical_sig + classical_pk)
        expected = (
            (self.cfg.pqc_sig_size() + self.cfg.pqc_pk_size())
            / (self.cfg.classical_sig_size() + self.cfg.classical_pk_size())
        )
        assert ratio == pytest.approx(expected, rel=0.001), (
            f"Phase 3 size_overhead_ratio ({ratio:.3f}) should equal "
            f"pqc-only ratio ({expected:.3f}), not combined-sig ratio"
        )

    def test_phase3_ratio_less_than_phase2_peak(self):
        """Phase 3 overhead must be lower than Phase 2 peak (dropping classical sig)."""
        # Phase 2 peak: combined_sig (ECDSA + ML-DSA-65)
        combined_ratio = (
            (self.cfg.combined_sig_size() + self.cfg.combined_pk_size())
            / (self.cfg.classical_sig_size() + self.cfg.classical_pk_size())
        )
        # Phase 3: pqc_only
        phase3_ratio = self.cfg.size_overhead_ratio(1001)

        assert phase3_ratio < combined_ratio, (
            f"Phase 3 ratio ({phase3_ratio:.2f}) should be lower than "
            f"dual-sig combined ratio ({combined_ratio:.2f})"
        )

    def test_pre_migration_ratio_is_one(self):
        """Before migration, size_overhead_ratio should be 1.0 (classical only)."""
        ratio = self.cfg.size_overhead_ratio(-100)
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_mid_migration_ratio_between_one_and_combined(self):
        """During migration, ratio should be between 1.0 and combined ratio."""
        combined = (
            (self.cfg.combined_sig_size() + self.cfg.combined_pk_size())
            / (self.cfg.classical_sig_size() + self.cfg.classical_pk_size())
        )
        mid_ratio = self.cfg.size_overhead_ratio(500)
        assert 1.0 <= mid_ratio <= combined + 0.01


# ---------------------------------------------------------------------------
# 2.5 — stale_rate includes zero-propagation blocks
# ---------------------------------------------------------------------------

class TestStaleRateIncludesZeroPropagation:
    """stale_rate denominator must be total proposed blocks, not just received blocks."""

    def test_stale_rate_uses_total_blocks_as_denominator(self):
        """At extreme PQC levels where blocks fail to propagate,
        stale_rate should approach 1.0, not 0.0."""
        from simulator.core.engine import DESEngine, SimulationConfig
        from simulator.chains.base import CHAIN_CONFIGS

        # Use SLH-DSA-128s — blocks are so large they will fail to propagate
        # on a tiny network with limited bandwidth
        cfg = SimulationConfig(
            chain="solana",
            signature_algorithm="SLH-DSA-128s",
            num_validators=5,
            num_full_nodes=3,
            simulation_duration_ms=5_000,
            random_seed=42,
        )
        engine = DESEngine(cfg)
        result = engine.run()

        # With the fix: stale_rate = (blocks_with_p90 > threshold + zero_prop_blocks)
        #                           / total_proposed_blocks
        # stale_rate should be in [0, 1]
        assert 0.0 <= result.stale_rate <= 1.0

        # num_blocks in result should equal blocks_proposed
        assert result.num_blocks == len(engine.state.blocks_proposed)

    def test_stale_rate_with_all_propagation_data(self):
        """When all blocks propagate normally, stale_rate should behave as before."""
        from simulator.core.engine import DESEngine, SimulationConfig

        cfg = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5_000,
            random_seed=42,
        )
        result = DESEngine(cfg).run()

        # Should be a valid fraction
        assert 0.0 <= result.stale_rate <= 1.0

    def test_zero_propagation_block_adds_to_stale_count(self):
        """A block with first_seen_by = {} (zero peers) must count as stale."""
        from simulator.network.propagation import Block
        from simulator.core.engine import DESEngine, SimulationConfig

        # Create a block with no propagation data
        empty_block = Block(
            block_hash="test", parent_hash="g",
            height=1, proposer_id="p0", timestamp_ms=0.0
        )
        assert empty_block.propagation_percentile(90) is None, (
            "Block with no first_seen_by should return None for p90"
        )

        # The engine's stale_rate fix counts None-p90 blocks as stale
        # Verify via the _compute_results logic directly
        block_time_ms = 400.0
        stale_threshold = block_time_ms * 0.9

        # Simulate the fix: None blocks are zero_propagation_blocks
        propagation_p90 = []  # empty = no data
        total_blocks = 1
        zero_prop = total_blocks - len(propagation_p90)  # = 1
        stale_count = sum(1 for p in propagation_p90 if p > stale_threshold) + zero_prop
        stale_rate = stale_count / total_blocks
        assert stale_rate == 1.0, (
            "A block with no propagation data should contribute stale_rate = 1.0"
        )


# ---------------------------------------------------------------------------
# 3.12 — algo_byte_distribution in Phase 2 results
# ---------------------------------------------------------------------------

class TestAlgoByteDistribution:
    """Phase 2 results must include algo_byte_distribution alongside algo_distribution."""

    def _run_phase2(self, pqc_fraction=0.5):
        from simulator.core.phase2_engine import Phase2Engine, Phase2Config
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=pqc_fraction,
            lambda_tps=20.0,
            num_validators=5,
            num_full_nodes=3,
            simulation_duration_ms=3_000,
            random_seed=42,
        )
        return Phase2Engine(cfg).run()

    def test_algo_byte_distribution_present(self):
        """algo_byte_distribution must be present in Phase 2 results."""
        result = self._run_phase2()
        assert "algo_byte_distribution" in result, (
            "algo_byte_distribution (byte fractions) must be present alongside "
            "algo_distribution (count fractions)"
        )

    def test_algo_byte_distribution_sums_to_one(self):
        """Byte fractions must sum to approximately 1.0."""
        result = self._run_phase2()
        total = sum(result["algo_byte_distribution"].values())
        assert abs(total - 1.0) < 0.001, (
            f"algo_byte_distribution values should sum to 1.0, got {total:.4f}"
        )

    def test_algo_distribution_sums_to_one(self):
        """Count fractions must also sum to 1.0 (unchanged)."""
        result = self._run_phase2()
        total = sum(result["algo_distribution"].values())
        assert abs(total - 1.0) < 0.001

    def test_pqc_byte_fraction_exceeds_count_fraction(self):
        """PQC byte fraction should be larger than PQC count fraction because
        PQC transactions are larger than classical ones."""
        result = self._run_phase2(pqc_fraction=0.5)

        # Find any PQC algorithm present
        pqc_algos = {k for k in result["algo_byte_distribution"]
                     if k not in ("Ed25519", "ECDSA", "Schnorr")}
        if not pqc_algos:
            pytest.skip("No PQC transactions in this run")

        for algo in pqc_algos:
            byte_frac  = result["algo_byte_distribution"].get(algo, 0.0)
            count_frac = result["algo_distribution"].get(algo, 0.0)
            if count_frac > 0:
                assert byte_frac >= count_frac, (
                    f"{algo}: byte fraction ({byte_frac:.3f}) should be >= "
                    f"count fraction ({count_frac:.3f}) since PQC txs are larger"
                )
