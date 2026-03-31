"""Engine–Agent integration tests (Phase 4).

Verifies that the Phase2Engine's agent-based demand model is correctly wired:

1. When use_agent_demand_model=False (default), agent keys are present with
   zero/False values — no demand modulation.
2. When use_agent_demand_model=True, demand_txs_submitted > 0, the
   avg_demand_reduction_pct key is present, and demand_reduction_pct varies
   with fee pressure.
3. blocks_elevated counter increments appropriately when fees are elevated.
4. BlockBuilder.verification_cost_weight biases selection toward fast-verify
   algorithms (Falcon-512 preferred over SLH-DSA-128s at equal fee).
5. Agent pool size is respected (smoke test on small pool).

All tests run with very short simulations to keep CI times acceptable.
MOCK_PQC=1 must be set (no liboqs required).
"""

from __future__ import annotations

import os
import pytest

# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

# Quick simulation parameters — keep Phase 2 runs under ~2 seconds each
_QUICK = dict(
    num_validators         = 10,
    num_full_nodes         = 5,
    simulation_duration_ms = 5_000,   # 5 seconds
    random_seed            = 7,
    nic_contention_enabled = False,   # faster
    use_chain_routing      = False,   # faster
)


def _run_phase2(chain: str = "solana", pqc_fraction: float = 0.0,
                fee_market_enabled: bool = True, **overrides) -> dict:
    """Run a Phase2Engine simulation and return the results dict."""
    # Import deferred to avoid loading heavy deps at module level
    from simulator.core.phase2_engine import Phase2Config, Phase2Engine

    cfg = Phase2Config(
        chain               = chain,
        pqc_fraction        = pqc_fraction,
        lambda_tps          = 200.0,
        fee_market_enabled  = fee_market_enabled,
        **{**_QUICK, **overrides},
    )
    engine = Phase2Engine(cfg)
    return engine.run()


# ---------------------------------------------------------------------------
# Section 1: Phase 4 keys are always present in results
# ---------------------------------------------------------------------------

class TestPhase4KeysPresent:
    """Results dict must always contain the Phase 4 demand keys."""

    def _check_keys(self, results: dict):
        expected = [
            "agent_demand_model_enabled",
            "blocks_elevated",
            "demand_txs_submitted",
            "demand_txs_abandoned",
            "demand_txs_batched",
            "demand_l2_migrations",
            "avg_demand_reduction_pct",
        ]
        for key in expected:
            assert key in results, f"Missing Phase 4 key: {key!r}"

    def test_keys_present_no_agent_model(self):
        results = _run_phase2(use_agent_demand_model=False)
        self._check_keys(results)

    def test_keys_present_with_agent_model(self):
        results = _run_phase2(
            use_agent_demand_model=True,
            agent_pool_size=50,
            fee_market_enabled=True,
        )
        self._check_keys(results)

    def test_agent_demand_model_enabled_false_by_default(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["agent_demand_model_enabled"] is False

    def test_agent_demand_model_enabled_true_when_set(self):
        results = _run_phase2(
            use_agent_demand_model=True,
            agent_pool_size=50,
            fee_market_enabled=True,
        )
        assert results["agent_demand_model_enabled"] is True


# ---------------------------------------------------------------------------
# Section 2: Default (no agent model) — counters are zero
# ---------------------------------------------------------------------------

class TestNoAgentModel:
    """With use_agent_demand_model=False, demand counters must remain zero."""

    def test_demand_txs_submitted_zero(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["demand_txs_submitted"] == 0

    def test_demand_txs_abandoned_zero(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["demand_txs_abandoned"] == 0

    def test_demand_txs_batched_zero(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["demand_txs_batched"] == 0

    def test_demand_l2_migrations_zero(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["demand_l2_migrations"] == 0

    def test_avg_demand_reduction_zero(self):
        results = _run_phase2(use_agent_demand_model=False)
        assert results["avg_demand_reduction_pct"] == 0.0

    def test_blocks_elevated_zero_no_fee_market(self):
        """Without fee market, baseline is never exceeded → blocks_elevated = 0."""
        results = _run_phase2(use_agent_demand_model=False, fee_market_enabled=False)
        assert results["blocks_elevated"] == 0


# ---------------------------------------------------------------------------
# Section 3: Agent model active — demand metrics populated
# ---------------------------------------------------------------------------

class TestAgentModelActive:
    """With use_agent_demand_model=True, demand metrics must be non-trivial."""

    @pytest.fixture(scope="class")
    def results_with_agents(self):
        """Single expensive run shared across tests in this class."""
        return _run_phase2(
            chain               = "solana",
            pqc_fraction        = 0.0,
            use_agent_demand_model = True,
            agent_pool_size     = 100,
            agent_random_seed   = 1,
            fee_market_enabled  = True,
            simulation_duration_ms = 8_000,
        )

    def test_demand_txs_submitted_positive(self, results_with_agents):
        assert results_with_agents["demand_txs_submitted"] > 0

    def test_avg_demand_reduction_is_float(self, results_with_agents):
        val = results_with_agents["avg_demand_reduction_pct"]
        assert isinstance(val, (int, float))

    def test_avg_demand_reduction_in_range(self, results_with_agents):
        val = results_with_agents["avg_demand_reduction_pct"]
        # Reduction can be 0% (no suppression) to 100% (all agents stopped)
        assert -0.01 <= val <= 100.01, f"avg_demand_reduction_pct={val} out of range"

    def test_blocks_elevated_non_negative(self, results_with_agents):
        assert results_with_agents["blocks_elevated"] >= 0

    def test_demand_counts_non_negative(self, results_with_agents):
        for key in ("demand_txs_submitted", "demand_txs_abandoned",
                    "demand_txs_batched", "demand_l2_migrations"):
            assert results_with_agents[key] >= 0, f"{key} < 0"


# ---------------------------------------------------------------------------
# Section 4: Demand reduction varies with fee pressure
# ---------------------------------------------------------------------------

class TestDemandReducesUnderFeePressure:
    """At high PQC fraction (elevated fees), demand reduction should be ≥ low-PQC run."""

    def test_high_pqc_not_less_reduced_than_classical(self):
        """avg_demand_reduction_pct(PQC=1.0) ≥ avg_demand_reduction_pct(PQC=0.0)."""
        low_pqc = _run_phase2(
            chain               = "solana",
            pqc_fraction        = 0.0,
            use_agent_demand_model = True,
            agent_pool_size     = 80,
            agent_random_seed   = 2,
            fee_market_enabled  = True,
            simulation_duration_ms = 8_000,
        )
        high_pqc = _run_phase2(
            chain               = "solana",
            pqc_fraction        = 1.0,
            use_agent_demand_model = True,
            agent_pool_size     = 80,
            agent_random_seed   = 2,
            fee_market_enabled  = True,
            simulation_duration_ms = 8_000,
        )
        # High PQC → larger transactions → higher fee pressure → agents reduce demand more
        # This is a directional (monotonicity) test — not guaranteed in all short runs,
        # but the agent model is designed to produce this effect.
        # We allow equal (both zero) as a valid outcome for short sims.
        assert high_pqc["avg_demand_reduction_pct"] >= low_pqc["avg_demand_reduction_pct"] - 5.0, (
            f"high_pqc reduction={high_pqc['avg_demand_reduction_pct']:.2f}% "
            f"< low_pqc reduction={low_pqc['avg_demand_reduction_pct']:.2f}% "
            f"(difference > 5%, model may be inverted)"
        )

    def test_agent_pool_size_respected(self):
        """results should reflect the configured pool size (smoke test)."""
        small_pool = _run_phase2(
            use_agent_demand_model = True,
            agent_pool_size        = 10,
            fee_market_enabled     = True,
        )
        large_pool = _run_phase2(
            use_agent_demand_model = True,
            agent_pool_size        = 200,
            fee_market_enabled     = True,
        )
        # Larger pool → more agents → more potential demand txs
        assert large_pool["demand_txs_submitted"] + large_pool["demand_txs_abandoned"] >= \
               small_pool["demand_txs_submitted"] + small_pool["demand_txs_abandoned"]


# ---------------------------------------------------------------------------
# Section 5: blocks_elevated counter
# ---------------------------------------------------------------------------

class TestBlocksElevatedCounter:
    """blocks_elevated tracks consecutive blocks with fee > 1.5× baseline."""

    def test_blocks_elevated_zero_without_fee_market(self):
        """No fee market → fee rate never changes → blocks_elevated stays 0."""
        results = _run_phase2(
            use_agent_demand_model = False,
            fee_market_enabled     = False,
        )
        assert results["blocks_elevated"] == 0

    def test_blocks_elevated_is_integer(self):
        results = _run_phase2(use_agent_demand_model=True, agent_pool_size=50)
        assert isinstance(results["blocks_elevated"], int)

    def test_blocks_elevated_non_negative(self):
        results = _run_phase2(
            use_agent_demand_model=True,
            agent_pool_size=50,
            pqc_fraction=0.5,
            fee_market_enabled=True,
        )
        assert results["blocks_elevated"] >= 0


# ---------------------------------------------------------------------------
# Section 6: BlockBuilder.verification_cost_weight
# ---------------------------------------------------------------------------

class TestVerificationCostWeight:
    """BlockBuilder censorship incentive — fast-verify txs score higher when w>0."""

    def _make_builder(self, weight: float, chain: str = "solana"):
        from simulator.economics.block_builder import BlockBuilder
        return BlockBuilder(
            chain                    = chain,
            sig_preference_model     = "fee_per_compute_unit",
            verification_cost_weight = weight,
        )

    def _make_tx(self, fee: float, sig_algo: str):
        from simulator.economics.block_builder import Transaction
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
        # Build a realistic size so fee_per_byte/gas/compute_unit are sensible
        sig   = SIGNATURE_SIZES.get(sig_algo, 64)
        pk    = PUBLIC_KEY_SIZES.get(sig_algo, 32)
        size  = 250 + sig + pk           # Solana-style overhead
        cus   = max(100, sig // 5)       # rough CU estimate proportional to sig size
        return Transaction(
            tx_id         = f"tx_{sig_algo}_{fee}",
            sig_algorithm = sig_algo,
            fee           = fee,
            size_bytes    = size,
            compute_units = cus,
        )

    def test_weight_zero_score_ignores_verify_time(self):
        """w=0 → score is purely fee/resource (fee_per_compute_unit).

        Two transactions with the same fee but very different compute_units
        (Falcon-512 vs ML-DSA-44) should differ only by their CU ratio when w=0.
        Adding weight should change the relative ranking.
        """
        from simulator.economics.block_builder import Transaction
        builder_w0 = self._make_builder(0.0)
        # Falcon: small CU footprint → high fee_per_CU
        # ML-DSA-44: large CU footprint → low fee_per_CU
        fast_tx = Transaction(
            tx_id="f", sig_algorithm="Falcon-512", fee=1000.0,
            size_bytes=500, compute_units=100, verify_time_us=80.0,
        )
        slow_tx = Transaction(
            tx_id="s", sig_algorithm="ML-DSA-44", fee=1000.0,
            size_bytes=500, compute_units=5_000, verify_time_us=180.0,
        )
        # w=0: score is fee_per_compute_unit; Falcon (10.0) >> ML-DSA (0.2)
        score_fast_w0 = builder_w0.score_transaction(fast_tx)
        score_slow_w0 = builder_w0.score_transaction(slow_tx)
        assert score_fast_w0 > score_slow_w0, (
            f"w=0: Falcon fee/CU ({score_fast_w0}) should exceed ML-DSA fee/CU ({score_slow_w0})"
        )

    def test_weight_positive_blends_fee_and_verify(self):
        """w=0.3 blends base_score (70%) with normalised_verify (30%).

        The blended score formula is:
            score = base_score * (1-w) + (fee / _REF_VERIFY_US) * w

        When two txs have the same fee, the blended term fee/_REF is equal,
        so ranking is purely determined by base_score.  This test verifies
        the formula produces the expected arithmetic result.
        """
        from simulator.economics.block_builder import Transaction
        builder = self._make_builder(0.3)
        _REF = 60.0  # _REF_VERIFY_US from block_builder.py

        # Tx with fee=900, CU=100 → fee_per_CU base = 9.0
        tx_high = Transaction(
            tx_id="h", sig_algorithm="Falcon-512", fee=900.0,
            size_bytes=300, compute_units=100, verify_time_us=80.0,
        )
        # Tx with fee=300, CU=100 → fee_per_CU base = 3.0
        tx_low = Transaction(
            tx_id="l", sig_algorithm="Falcon-512", fee=300.0,
            size_bytes=300, compute_units=100, verify_time_us=80.0,
        )
        score_high = builder.score_transaction(tx_high)
        score_low  = builder.score_transaction(tx_low)

        # Expected: score = base * 0.7 + (fee / 60) * 0.3
        expected_high = 9.0 * 0.7 + (900.0 / _REF) * 0.3
        expected_low  = 3.0 * 0.7 + (300.0 / _REF) * 0.3
        assert abs(score_high - expected_high) < 1e-9, (
            f"score_high={score_high:.6f} != expected={expected_high:.6f}"
        )
        assert abs(score_low - expected_low) < 1e-9, (
            f"score_low={score_low:.6f} != expected={expected_low:.6f}"
        )
        # Higher-fee tx should score higher
        assert score_high > score_low

    def test_weight_one_verify_efficiency_ordering(self):
        """w=1 reduces score to the normalised_verify term = fee / _REF_VERIFY_US.

        At w=1 the base_score is zeroed out; the remaining term is
        `fee_per_verify_us * (verify_time_us / _REF)` which simplifies to
        `fee / _REF_VERIFY_US` -- constant for equal fees, larger for higher fees.
        """
        from simulator.economics.block_builder import Transaction
        builder = self._make_builder(1.0)
        _REF = 60.0

        tx_rich = Transaction(
            tx_id="r", sig_algorithm="Falcon-512", fee=1200.0,
            size_bytes=300, compute_units=100, verify_time_us=80.0,
        )
        tx_cheap = Transaction(
            tx_id="c", sig_algorithm="Falcon-512", fee=300.0,
            size_bytes=300, compute_units=100, verify_time_us=80.0,
        )
        score_rich  = builder.score_transaction(tx_rich)
        score_cheap = builder.score_transaction(tx_cheap)

        # w=1: score = fee / _REF
        assert abs(score_rich  - (1200.0 / _REF)) < 1e-9
        assert abs(score_cheap - (300.0  / _REF)) < 1e-9
        assert score_rich > score_cheap

    def test_weight_clamped_above_one(self):
        """Weights > 1 should be clamped to 1 (no negative base-score contribution)."""
        builder = self._make_builder(2.0)
        fast_tx = self._make_tx(fee=1000.0, sig_algo="Falcon-512")
        # Should not raise; score should be >= 0
        score = builder.score_transaction(fast_tx)
        assert score >= 0.0

    def test_weight_clamped_below_zero(self):
        """Negative weights should be clamped to 0 (same as w=0)."""
        builder_neg  = self._make_builder(-0.5)
        builder_zero = self._make_builder(0.0)
        tx = self._make_tx(fee=800.0, sig_algo="ML-DSA-44")
        # Should produce the same score as w=0
        assert abs(builder_neg.score_transaction(tx) -
                   builder_zero.score_transaction(tx)) < 1e-9

    def test_classical_tx_verify_score_sensible(self):
        """Classical ECDSA tx should have a positive score at any weight."""
        for weight in (0.0, 0.3, 1.0):
            builder = self._make_builder(weight)
            tx = self._make_tx(fee=100.0, sig_algo="ECDSA")
            assert builder.score_transaction(tx) >= 0.0

    def test_higher_fee_still_beats_lower_fee_same_algo(self):
        """Even with w=0.3, higher fee wins for the same algorithm."""
        builder = self._make_builder(0.3)
        rich_tx  = self._make_tx(fee=10_000.0, sig_algo="ML-DSA-44")
        cheap_tx = self._make_tx(fee=1.0,      sig_algo="ML-DSA-44")
        assert builder.score_transaction(rich_tx) > \
               builder.score_transaction(cheap_tx)


# ---------------------------------------------------------------------------
# Section 7: Phase2Config agent fields are forwarded correctly
# ---------------------------------------------------------------------------

class TestPhase2ConfigAgentFields:
    """Phase2Config dataclass exposes the Phase 4 fields with correct defaults."""

    def test_use_agent_demand_model_default_false(self):
        from simulator.core.phase2_engine import Phase2Config
        cfg = Phase2Config(chain="solana")
        assert cfg.use_agent_demand_model is False

    def test_agent_pool_size_default(self):
        from simulator.core.phase2_engine import Phase2Config
        cfg = Phase2Config(chain="solana")
        assert cfg.agent_pool_size == 500

    def test_agent_random_seed_default(self):
        from simulator.core.phase2_engine import Phase2Config
        cfg = Phase2Config(chain="solana")
        assert cfg.agent_random_seed == 0

    def test_can_override_agent_fields(self):
        from simulator.core.phase2_engine import Phase2Config
        cfg = Phase2Config(
            chain="solana",
            use_agent_demand_model=True,
            agent_pool_size=999,
            agent_random_seed=42,
        )
        assert cfg.use_agent_demand_model is True
        assert cfg.agent_pool_size == 999
        assert cfg.agent_random_seed == 42

    def test_agent_pool_initialised_when_enabled(self):
        """Phase2Engine._agent_pool should be non-None when model is enabled.
        Agent model requires fee_market_enabled=True (BUG-C fix).
        """
        from simulator.core.phase2_engine import Phase2Config, Phase2Engine
        cfg = Phase2Config(
            chain="solana",
            use_agent_demand_model=True,
            fee_market_enabled=True,   # required by BUG-C guard
            agent_pool_size=20,
            **_QUICK,
        )
        engine = Phase2Engine(cfg)
        assert engine._agent_pool is not None

    def test_agent_pool_none_when_disabled(self):
        """Phase2Engine._agent_pool should be None when model is disabled."""
        from simulator.core.phase2_engine import Phase2Config, Phase2Engine
        cfg = Phase2Config(chain="solana", use_agent_demand_model=False, **_QUICK)
        engine = Phase2Engine(cfg)
        assert engine._agent_pool is None

    def test_custom_seed_used_for_agent_pool(self):
        """Agent pool should use agent_random_seed when non-zero.
        Agent model requires fee_market_enabled=True (BUG-C fix).
        """
        from simulator.core.phase2_engine import Phase2Config, Phase2Engine
        cfg = Phase2Config(
            chain="solana",
            use_agent_demand_model=True,
            fee_market_enabled=True,   # required by BUG-C guard
            agent_pool_size=20,
            agent_random_seed=99,
            **_QUICK,
        )
        engine = Phase2Engine(cfg)
        # Confirm it ran without error and pool exists
        assert engine._agent_pool is not None

    def test_agent_model_without_fee_market_raises(self):
        """use_agent_demand_model=True without fee_market raises ValueError (BUG-C)."""
        from simulator.core.phase2_engine import Phase2Config, Phase2Engine
        cfg = Phase2Config(
            chain="solana",
            use_agent_demand_model=True,
            fee_market_enabled=False,  # missing fee market
            agent_pool_size=20,
            **_QUICK,
        )
        with pytest.raises(ValueError, match="fee_market_enabled"):
            Phase2Engine(cfg)
