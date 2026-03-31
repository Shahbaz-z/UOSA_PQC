"""Tests for simulator/economics/user_agents.py.

Covers UserAgent decision logic for each archetype, AgentPool generation,
and block-level demand simulation.
"""

import pytest
from simulator.economics.user_agents import (
    UserAgent,
    AgentPool,
    AGENT_DEFAULTS,
    CHAIN_AGENT_MIX,
)


def make_agent(agent_type: str, **kwargs) -> UserAgent:
    """Helper: construct a UserAgent from defaults + overrides."""
    defaults = AGENT_DEFAULTS[agent_type]
    return UserAgent(
        agent_type                   = agent_type,
        wallet_balance_usd           = kwargs.get("wallet_balance_usd", defaults["wallet_balance_usd_mean"]),
        tx_value_usd                 = kwargs.get("tx_value_usd", defaults["tx_value_usd_mean"]),
        max_fee_ratio                = defaults["max_fee_ratio"],
        batch_threshold_ratio        = defaults["batch_threshold_ratio"],
        l2_migration_threshold_ratio = defaults["l2_migration_threshold_ratio"],
        l2_migration_min_blocks      = defaults["l2_migration_min_blocks"],
        delay_tolerance_slots        = defaults["delay_tolerance_slots"],
        random_seed                  = 42,
    )


class TestRetailAgent:
    def test_submits_at_baseline(self):
        agent = make_agent("retail")
        assert agent.will_submit(1.0, 1.0) is True

    def test_abandons_at_high_fee(self):
        agent = make_agent("retail")
        # Retail threshold is 2× for batching, but should abandon well above that
        # The batch threshold is 2×, so above that will_submit returns False
        assert agent.will_submit(10.0, 1.0) is False

    def test_batches_at_2x(self):
        agent = make_agent("retail")
        # batch_threshold_ratio = 2.0 for retail
        assert agent.will_batch(2.5, 1.0) is True

    def test_does_not_batch_at_baseline(self):
        agent = make_agent("retail")
        assert agent.will_batch(1.0, 1.0) is False

    def test_migrates_l2_with_sustained_pressure(self):
        agent = make_agent("retail")
        # l2_migration_threshold_ratio = 5.0, l2_migration_min_blocks = 50
        assert agent.will_migrate_l2(6.0, 1.0, blocks_elevated=100) is True

    def test_does_not_migrate_l2_without_sustained_pressure(self):
        agent = make_agent("retail")
        assert agent.will_migrate_l2(6.0, 1.0, blocks_elevated=10) is False


class TestWhaleAgent:
    def test_submits_at_high_fee(self):
        agent = make_agent("whale")
        # Whale batch threshold is 20× — should still submit at 15×
        assert agent.will_submit(15.0, 1.0) is True

    def test_batch_threshold_is_high(self):
        agent = make_agent("whale")
        # Whale should not batch at 5×
        assert agent.will_batch(5.0, 1.0) is False


class TestArbBotAgent:
    def test_does_not_batch(self):
        agent = make_agent("arb_bot")
        # Arb bots are time-sensitive; batch threshold is very high
        assert agent.will_batch(5.0, 1.0) is False

    def test_delay_tolerance_is_very_low(self):
        agent = make_agent("arb_bot")
        assert agent.delay_tolerance_slots <= 3


class TestDeFiProtocolAgent:
    def test_migrates_l2_with_sustained_fee(self):
        agent = make_agent("defi_protocol")
        # l2_migration_threshold = 5.0, min_blocks = 100
        assert agent.will_migrate_l2(6.0, 1.0, blocks_elevated=200) is True

    def test_does_not_migrate_too_quickly(self):
        agent = make_agent("defi_protocol")
        assert agent.will_migrate_l2(6.0, 1.0, blocks_elevated=50) is False


class TestExchangeAgent:
    def test_batches_quickly(self):
        agent = make_agent("exchange")
        # Exchange batch threshold is 1.5×
        assert agent.will_batch(2.0, 1.0) is True

    def test_batch_size_scales_with_fee(self):
        agent = make_agent("exchange")
        small_batch = agent.batch_size(2.0, 1.0)
        large_batch = agent.batch_size(10.0, 1.0)
        assert large_batch >= small_batch

    def test_batch_size_is_1_at_baseline(self):
        agent = make_agent("exchange")
        assert agent.batch_size(1.0, 1.0) == 1


class TestEffectiveTxSize:
    def test_batching_reduces_effective_size(self):
        agent = make_agent("exchange")
        size_single = agent.effective_tx_size_bytes("ML-DSA-65", batch_size=1)
        size_batched = agent.effective_tx_size_bytes("ML-DSA-65", batch_size=10)
        assert size_batched < size_single

    def test_pqc_larger_than_classical(self):
        agent = make_agent("retail")
        classical = agent.effective_tx_size_bytes("ECDSA")
        pqc = agent.effective_tx_size_bytes("ML-DSA-65")
        assert pqc > classical

    def test_positive_for_all_algos(self):
        agent = make_agent("retail")
        for algo in ["ECDSA", "Ed25519", "ML-DSA-65", "Falcon-512"]:
            assert agent.effective_tx_size_bytes(algo) > 0


class TestAgentPool:
    def test_pool_generates_agents(self):
        pool = AgentPool(chain="ethereum", pool_size=100, seed=42)
        assert len(pool.agents) > 0

    def test_pool_size_approximately_correct(self):
        pool = AgentPool(chain="ethereum", pool_size=200, seed=42)
        # Allow ±20% due to rounding of fractions
        assert 160 <= len(pool.agents) <= 240

    def test_all_chains_produce_agents(self):
        for chain in ["bitcoin", "ethereum", "solana"]:
            pool = AgentPool(chain=chain, pool_size=100, seed=42)
            assert len(pool.agents) > 0

    def test_agents_by_type(self):
        pool = AgentPool(chain="ethereum", pool_size=500, seed=42)
        arbs = pool.agents_by_type("arb_bot")
        assert len(arbs) > 0

    def test_simulate_block_demand_keys(self):
        pool = AgentPool(chain="ethereum", pool_size=200, seed=42)
        demand = pool.simulate_block_demand(
            current_fee_rate  = 1.0,
            baseline_fee_rate = 1.0,
            sig_algorithm     = "ECDSA",
        )
        for key in ["txs_submitted", "txs_abandoned", "l2_migrations",
                    "submission_rate", "demand_reduction_pct"]:
            assert key in demand

    def test_demand_reduction_increases_with_fee(self):
        pool = AgentPool(chain="ethereum", pool_size=300, seed=42)
        demand_low  = pool.simulate_block_demand(1.0, 1.0, "ECDSA")
        demand_high = pool.simulate_block_demand(15.0, 1.0, "ECDSA")
        assert demand_high["demand_reduction_pct"] >= demand_low["demand_reduction_pct"]

    def test_submission_rate_is_fraction(self):
        pool = AgentPool(chain="ethereum", pool_size=100, seed=42)
        demand = pool.simulate_block_demand(1.0, 1.0, "ML-DSA-65")
        assert 0.0 <= demand["submission_rate"] <= 1.0

    def test_elasticity_curve_monotonically_decreasing_submissions(self):
        pool = AgentPool(chain="ethereum", pool_size=300, seed=42)
        curve = pool.fee_elasticity_curve(
            baseline_fee_rate = 1.0,
            max_multiplier    = 10.0,
            steps             = 5,
            sig_algorithm     = "ECDSA",
        )
        submissions = [c["txs_submitted"] for c in curve]
        # Submissions should be non-increasing as fees rise
        for i in range(len(submissions) - 1):
            assert submissions[i] >= submissions[i + 1]

    def test_chain_agent_mix_sums_to_one(self):
        for chain, mix in CHAIN_AGENT_MIX.items():
            total = sum(mix.values())
            assert abs(total - 1.0) < 0.01, f"Mix for {chain} doesn't sum to 1.0"
