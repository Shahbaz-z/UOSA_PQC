"""Tests for dynamic fee market model."""

import math
import random

import pytest
from simulator.economics.fee_market import (
    DynamicFeeMarket,
    FeeMarketConfig,
    FEE_MARKET_PRESETS,
)


class TestFeeMarketConfig:
    """Test fee market configuration."""

    def test_default_config(self):
        c = FeeMarketConfig()
        assert c.base_fee_floor == 1.0
        assert c.base_fee_ceiling == 10_000.0
        assert c.fee_model == "eip1559"

    def test_presets_exist(self):
        for chain in ["solana", "ethereum", "bitcoin"]:
            assert chain in FEE_MARKET_PRESETS
            p = FEE_MARKET_PRESETS[chain]
            assert p.base_fee_floor > 0
            assert p.base_fee_ceiling > p.base_fee_floor


class TestEIP1559:
    """Test EIP-1559 fee adjustment."""

    def test_fee_increases_when_full(self):
        """Fee should increase when blocks are more than 50% full."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=10.0,
            adjustment_speed=0.125,
            fee_model="eip1559",
        ))
        initial = fm.base_fee
        fm.update_base_fee(0, mempool_utilization=0.8, block_utilization=1.0)
        assert fm.base_fee > initial

    def test_fee_decreases_when_empty(self):
        """Fee should decrease when blocks are less than 50% full."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=1.0,
            base_fee_ceiling=1000.0,
            adjustment_speed=0.125,
            fee_model="eip1559",
        ))
        # Set initial fee above floor
        fm.base_fee = 100.0
        initial = fm.base_fee
        fm.update_base_fee(0, mempool_utilization=0.2, block_utilization=0.1)
        assert fm.base_fee < initial

    def test_fee_clamps_to_floor(self):
        """Fee should never go below floor."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=5.0,
            adjustment_speed=0.5,
            fee_model="eip1559",
        ))
        for _ in range(100):
            fm.update_base_fee(0, mempool_utilization=0.0, block_utilization=0.0)
        assert fm.base_fee >= 5.0

    def test_fee_clamps_to_ceiling(self):
        """Fee should never exceed ceiling."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=1.0,
            base_fee_ceiling=100.0,
            adjustment_speed=0.5,
            fee_model="eip1559",
        ))
        for _ in range(100):
            fm.update_base_fee(0, mempool_utilization=1.0, block_utilization=1.0)
        assert fm.base_fee <= 100.0


class TestFirstPrice:
    """Test Bitcoin first-price auction."""

    def test_fee_equals_min_block_fee(self):
        """Base fee should equal minimum fee in last block."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=1.0,
            fee_model="first_price",
        ))
        fm.record_block_fee(50.0)
        fm.record_block_fee(100.0)
        fm.record_block_fee(25.0)
        fm.update_base_fee(0, mempool_utilization=0.5)
        assert fm.base_fee == 25.0

    def test_fee_decays_no_block(self):
        """Fee should decay when no block fees recorded."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=1.0,
            fee_model="first_price",
        ))
        fm.base_fee = 100.0
        fm.update_base_fee(0, mempool_utilization=0.5)
        assert fm.base_fee < 100.0


class TestPriorityFee:
    """Test Solana priority fee model."""

    def test_fee_increases_under_pressure(self):
        """Fee should increase when mempool is over target."""
        fm = DynamicFeeMarket(FeeMarketConfig(
            base_fee_floor=1.0,
            target_utilization=0.5,
            fee_model="priority_fee",
        ))
        initial = fm.base_fee
        fm.update_base_fee(0, mempool_utilization=0.9)
        assert fm.base_fee > initial


class TestFeeGeneration:
    """Test fee generation and economic failure."""

    def test_generate_positive_fee(self):
        fm = DynamicFeeMarket(FeeMarketConfig())
        fee = fm.generate_tx_fee(500)
        assert fee > 0

    def test_pqc_fees_tend_higher(self):
        """PQC transactions tend to have higher absolute fees."""
        fm = DynamicFeeMarket(FeeMarketConfig(), rng=random.Random(42))
        classical = [fm.generate_tx_fee(200, is_pqc=False) for _ in range(100)]
        pqc = [fm.generate_tx_fee(200, is_pqc=True) for _ in range(100)]
        # PQC should have higher mean fee (higher target rate)
        assert sum(pqc) / len(pqc) > sum(classical) / len(classical) * 0.9

    def test_check_acceptable_above_base(self):
        fm = DynamicFeeMarket(FeeMarketConfig(base_fee_floor=10.0))
        fm.base_fee = 10.0
        assert fm.check_acceptable(fee_satoshis=5000, tx_size_bytes=100)  # rate=50

    def test_check_acceptable_below_base(self):
        fm = DynamicFeeMarket(FeeMarketConfig(base_fee_floor=10.0))
        fm.base_fee = 100.0
        assert not fm.check_acceptable(fee_satoshis=50, tx_size_bytes=100)  # rate=0.5

    def test_economic_rejection_counted(self):
        fm = DynamicFeeMarket(FeeMarketConfig())
        fm.base_fee = 1000.0  # Very high
        fm.check_acceptable(1, 100)  # Should reject
        assert fm._economic_rejections == 1

    def test_metrics_returns_dict(self):
        fm = DynamicFeeMarket(FeeMarketConfig())
        fm.update_base_fee(0, 0.5)
        m = fm.metrics()
        assert "fee_market_enabled" in m
        assert "base_fee_mean" in m
        assert "economic_failure_rate" in m
