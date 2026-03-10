"""Tests for validator economics model."""

import math
import pytest
from simulator.economics.validator_economics import (
    ValidatorEconomicsConfig,
    ValidatorEconomicsModel,
    VALIDATOR_PRESETS,
)


class TestValidatorEconomicsConfig:
    """Test config and cost computation."""

    def test_cost_per_slot(self):
        cfg = ValidatorEconomicsConfig(
            hardware_monthly_usd=1500.0,
            bandwidth_monthly_usd=200.0,
            vote_cost_per_slot_usd=0.01,
            slots_per_month=6_480_000.0,
        )
        # Fixed per slot = (1500+200)/6480000 ≈ 0.000262
        # Total = 0.000262 + 0.01 ≈ 0.010262
        assert cfg.cost_per_slot_usd > 0.01
        assert cfg.cost_per_slot_usd < 0.02

    def test_presets_exist(self):
        for chain in ["solana", "ethereum", "bitcoin"]:
            assert chain in VALIDATOR_PRESETS


class TestBreakEven:
    """Test break-even stale rate calculation."""

    def test_solana_break_even(self):
        """Solana: R=0.05, c≈0.01 → s_max ≈ 1 - 0.01/0.05 = 0.80."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        s_be = model.break_even_stale_rate()
        # Should be positive and < 1.0
        assert 0.0 < s_be < 1.0
        # Roughly: 1 - c/R
        R = VALIDATOR_PRESETS["solana"].block_reward_per_slot_usd
        c = VALIDATOR_PRESETS["solana"].cost_per_slot_usd
        expected = 1.0 - c / R
        assert abs(s_be - expected) < 0.001

    def test_bitcoin_no_reward(self):
        """Bitcoin full nodes have no reward → break-even = 1.0."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["bitcoin"])
        assert model.break_even_stale_rate() == 1.0

    def test_ethereum_break_even(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["ethereum"])
        s_be = model.break_even_stale_rate()
        assert 0.0 < s_be < 1.0


class TestProfitMargin:
    """Test profit margin calculation."""

    def test_zero_stale_rate(self):
        """At 0% stale: margin = (R-c)/R."""
        cfg = ValidatorEconomicsConfig(
            block_reward_per_slot_usd=1.0,
            vote_cost_per_slot_usd=0.0,
            hardware_monthly_usd=0.0,
            bandwidth_monthly_usd=0.0,
        )
        model = ValidatorEconomicsModel(cfg)
        assert model.profit_margin(0.0) == pytest.approx(1.0, abs=0.01)

    def test_margin_decreases_with_stale(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        m0 = model.profit_margin(0.0)
        m50 = model.profit_margin(0.5)
        m100 = model.profit_margin(1.0)
        assert m0 > m50 > m100

    def test_bitcoin_always_negative(self):
        """Bitcoin full nodes always have negative margin (no reward)."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["bitcoin"])
        assert model.profit_margin(0.0) == -1.0


class TestExitProbability:
    """Test sigmoid exit probability."""

    def test_low_stale_low_exit(self):
        """Far below break-even: exit probability ≈ 0."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        p = model.exit_probability(0.0)
        assert p < 0.01

    def test_at_break_even_50pct(self):
        """At break-even: exit probability ≈ 50%."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        s_be = model.break_even_stale_rate()
        p = model.exit_probability(s_be)
        assert abs(p - 0.5) < 0.05

    def test_high_stale_high_exit(self):
        """Far above break-even: exit probability ≈ 1."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        p = model.exit_probability(0.99)
        assert p > 0.95

    def test_monotonically_increasing(self):
        """Exit probability should increase with stale rate."""
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        stale_rates = [0.0, 0.2, 0.5, 0.8, 1.0]
        probs = [model.exit_probability(s) for s in stale_rates]
        for i in range(len(probs) - 1):
            assert probs[i] <= probs[i + 1]


class TestNetworkShrinkage:
    """Test network shrinkage estimation."""

    def test_no_shrinkage_at_zero_stale(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        exits, remaining = model.network_shrinkage(0.0, 1500)
        assert exits == 0
        assert remaining == 1.0

    def test_full_shrinkage_at_extreme(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        exits, remaining = model.network_shrinkage(0.99, 1500)
        assert exits > 0
        assert remaining < 1.0

    def test_returns_tuple(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        result = model.network_shrinkage(0.5, 100)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestComputeMetrics:
    """Test the full metrics computation."""

    def test_returns_all_keys(self):
        model = ValidatorEconomicsModel(VALIDATOR_PRESETS["solana"])
        m = model.compute_metrics(0.1, 1500)
        required_keys = [
            "break_even_stale_rate",
            "profit_margin",
            "exit_probability",
            "estimated_validator_exits",
            "remaining_validators_fraction",
        ]
        for k in required_keys:
            assert k in m, f"Missing key: {k}"
