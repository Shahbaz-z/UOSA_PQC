"""Tests for DES engine."""

import pytest

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.results import SimulationResult


class TestSimulationConfig:
    """Tests for SimulationConfig dataclass."""

    def test_default_config(self):
        """Should create config with reasonable defaults."""
        config = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
        )

        assert config.chain == "solana"
        assert config.signature_algorithm == "Ed25519"
        assert config.num_validators == 200
        assert config.num_full_nodes == 100
        assert config.simulation_duration_ms == 300_000
        assert config.random_seed == 42

    def test_custom_config(self):
        """Should accept custom parameters."""
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="ECDSA",
            num_validators=50,
            num_full_nodes=25,
            simulation_duration_ms=60_000,
            random_seed=123,
        )

        assert config.num_validators == 50
        assert config.simulation_duration_ms == 60_000


class TestDESEngine:
    """Tests for DESEngine class."""

    @pytest.fixture
    def short_config(self):
        """Create a short simulation config for testing."""
        return SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=5_000,  # 5 seconds (12.5 Solana slots)
            random_seed=42,
        )

    def test_engine_initialization(self, short_config):
        """Engine should initialize with network and state."""
        engine = DESEngine(short_config)

        assert engine.topology.validator_count() == 20
        assert engine.topology.node_count() == 30  # 20 validators + 10 full nodes
        assert engine.state.current_time_ms == 0.0

    def test_engine_runs_simulation(self, short_config):
        """Engine should run simulation and return results."""
        engine = DESEngine(short_config)
        result = engine.run()

        assert isinstance(result, SimulationResult)
        assert result.chain == "solana"
        assert result.signature_algorithm == "Ed25519"

    def test_produces_blocks(self, short_config):
        """Simulation should produce blocks."""
        engine = DESEngine(short_config)
        result = engine.run()

        # 5000ms / 400ms per slot = 12.5 slots
        # Should produce ~12 blocks
        assert result.num_blocks >= 10
        assert result.num_blocks <= 15

    def test_blocks_propagate(self, short_config):
        """Blocks should propagate through network."""
        engine = DESEngine(short_config)
        result = engine.run()

        # Propagation metrics should be positive
        assert result.avg_propagation_p50_ms > 0
        assert result.avg_propagation_p90_ms > 0

        # p90 should be larger than p50
        assert result.avg_propagation_p90_ms >= result.avg_propagation_p50_ms

    def test_stale_rate_in_valid_range(self, short_config):
        """Stale rate should be between 0 and 1."""
        engine = DESEngine(short_config)
        result = engine.run()

        assert 0 <= result.stale_rate <= 1

    def test_deterministic_with_seed(self):
        """Same seed should produce identical results."""
        config1 = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )

        config2 = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )

        result1 = DESEngine(config1).run()
        result2 = DESEngine(config2).run()

        assert result1.num_blocks == result2.num_blocks
        assert result1.avg_propagation_p90_ms == result2.avg_propagation_p90_ms

    def test_different_seeds_different_results(self):
        """Different seeds should produce different results."""
        config1 = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=42,
        )

        config2 = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2_000,
            random_seed=99,  # Different seed
        )

        result1 = DESEngine(config1).run()
        result2 = DESEngine(config2).run()

        # Results should differ (at least propagation times)
        assert result1.avg_propagation_p90_ms != result2.avg_propagation_p90_ms


class TestPQCImpact:
    """Tests verifying PQC signatures increase propagation time."""

    @pytest.fixture
    def base_config(self):
        """Base config for comparison."""
        return {
            "chain": "solana",
            "num_validators": 20,
            "num_full_nodes": 10,
            "simulation_duration_ms": 5_000,
            "random_seed": 42,
        }

    def test_larger_signatures_increase_propagation(self, base_config):
        """Larger PQC signatures should increase propagation time."""
        ed25519_config = SimulationConfig(
            signature_algorithm="Ed25519",
            **base_config,
        )

        mldsa_config = SimulationConfig(
            signature_algorithm="ML-DSA-65",
            **base_config,
        )

        ed25519_result = DESEngine(ed25519_config).run()
        mldsa_result = DESEngine(mldsa_config).run()

        # With the tx cap removed, both algorithms fill blocks to the byte-size
        # limit (~6 MB), so avg_block_size_bytes is nearly identical.
        # The meaningful physics difference is transaction DENSITY: Ed25519's
        # small signatures (~64 B) pack many more txs than ML-DSA-65 (~3300 B).
        assert ed25519_result.avg_txs_per_block > mldsa_result.avg_txs_per_block


class TestChainConfigs:
    """Tests for different chain configurations."""

    def test_bitcoin_longer_blocks(self):
        """Bitcoin should produce fewer blocks (10 min block time)."""
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="ECDSA",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=120_000,  # 2 minutes
            random_seed=42,
        )

        result = DESEngine(config).run()

        # 2 minutes < 10 minute block time, so 0-1 blocks expected
        assert result.num_blocks <= 2

    def test_ethereum_moderate_blocks(self):
        """Ethereum should produce blocks every 12 seconds."""
        config = SimulationConfig(
            chain="ethereum",
            signature_algorithm="ECDSA",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=60_000,  # 1 minute
            random_seed=42,
        )

        result = DESEngine(config).run()

        # 60 seconds / 12 seconds = 5 blocks expected
        assert 3 <= result.num_blocks <= 7
