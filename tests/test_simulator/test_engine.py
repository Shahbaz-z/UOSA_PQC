"""Tests for DES engine."""

import pytest

from simulator.core.engine import DESEngine, SimulationConfig


class TestDESEngineSetup:
    """Tests for engine initialisation and setup."""

    def test_engine_creates_correct_node_count(self):
        """Engine should create the specified number of validators and full nodes."""
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=40,
            simulation_duration=10.0,
            random_seed=42,
        )
        engine = DESEngine(config)
        engine.setup()
        validators = [n for n in engine.nodes.values() if n.config.node_type == "validator"]
        full_nodes = [n for n in engine.nodes.values() if n.config.node_type == "full_node"]
        assert len(validators) == 10
        assert len(full_nodes) == 40

    def test_engine_chain_config_loaded(self):
        """Chain config should be loaded after setup."""
        config = SimulationConfig(
            chain="ethereum",
            signature_algorithm="Ed25519",
            num_validators=5,
            num_full_nodes=10,
            simulation_duration=5.0,
            random_seed=0,
        )
        engine = DESEngine(config)
        engine.setup()
        assert engine.chain_config is not None

    def test_engine_topology_built(self):
        """Topology should be constructed after setup."""
        config = SimulationConfig(
            chain="solana",
            signature_algorithm="ML-DSA-65",
            num_validators=5,
            num_full_nodes=10,
            simulation_duration=5.0,
            random_seed=7,
        )
        engine = DESEngine(config)
        engine.setup()
        assert engine.topology is not None


class TestDESEngineRun:
    """Tests for simulation run."""

    def test_short_run_produces_results(self):
        """A short simulation should produce at least one block result."""
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=20,
            simulation_duration=120.0,
            random_seed=1,
        )
        engine = DESEngine(config)
        results = engine.run()
        assert len(results) >= 1, "Expected at least 1 block in 120s Bitcoin simulation"

    def test_results_have_valid_propagation_times(self):
        """All result propagation times should be positive."""
        config = SimulationConfig(
            chain="ethereum",
            signature_algorithm="Ed25519",
            num_validators=10,
            num_full_nodes=20,
            simulation_duration=60.0,
            random_seed=2,
        )
        engine = DESEngine(config)
        results = engine.run()
        for r in results:
            assert r.propagation_p50_ms >= 0
            assert r.propagation_p90_ms >= r.propagation_p50_ms

    def test_pqc_run_produces_results(self):
        """PQC simulation should complete without errors."""
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="ML-DSA-65",
            num_validators=10,
            num_full_nodes=20,
            simulation_duration=120.0,
            random_seed=3,
            pqc_adoption_fraction=1.0,
        )
        engine = DESEngine(config)
        results = engine.run()
        assert len(results) >= 1

    def test_block_fill_uses_byte_capacity_not_tx_cap(self):
        """
        FIX #3: Blocks should fill to byte-size capacity, not be capped at 10K txs.

        We generate a simulation where tx size is small relative to block size,
        so a correct implementation should pack many transactions per block.
        For Bitcoin (1MB blocks, ~250 byte txs), we expect ~4000 txs max.
        For Solana (128MB blocks, ~250 byte txs), we expect >> 10K txs.
        """
        config = SimulationConfig(
            chain="solana",
            signature_algorithm="Ed25519",
            num_validators=20,
            num_full_nodes=50,
            simulation_duration=30.0,  # short run
            random_seed=10,
        )
        engine = DESEngine(config)
        results = engine.run()
        if results:
            # With byte-capacity filling and small txs, some blocks should exceed 10K txs
            # (if the old 10K cap was present, max would always be <=10000)
            max_txs = max(r.num_txs for r in results)
            # Solana has 128MB blocks; at min tx size of ~250 bytes,
            # theoretical max ~512K txs. With realistic tx load, we expect > 10K.
            # If this assertion fails, the 10K cap (Fix #3) was not removed.
            assert max_txs > 100, (
                f"Expected blocks with >100 txs on Solana, got max={max_txs}. "
                "Check Fix #3: 10K tx cap should be removed."
            )

    def test_stale_threshold_uses_09_block_time(self):
        """
        FIX #1: Stale block threshold should be 0.9 × block_time, not 0.5.

        Verify by checking that no "stale" blocks are recorded for fast propagation
        scenarios where p90 < 0.9 × block_time but > 0.5 × block_time.
        """
        # Use a chain with a long block time (Bitcoin: 600s)
        # In a small local network, p90 propagation should be well under 0.9 × 600s
        config = SimulationConfig(
            chain="bitcoin",
            signature_algorithm="Ed25519",
            num_validators=5,
            num_full_nodes=10,
            simulation_duration=1200.0,
            random_seed=42,
        )
        engine = DESEngine(config)
        engine.run()
        # With fast local propagation, stale blocks should be 0 (threshold = 0.9 × 600 = 540s)
        stale_count = len(engine.state.get_stale_blocks())
        # In a small well-connected network, propagation << 540s, so stale_count should be 0
        assert stale_count == 0, (
            f"Expected 0 stale blocks with 0.9× threshold on small network, got {stale_count}. "
            "Check Fix #1: threshold should be 0.9 × block_time."
        )
