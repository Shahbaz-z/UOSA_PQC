"""Tests for multi-chain DES engine support (Phase B).

Validates that:
1. All three chains can run full Phase 1 simulations
2. All three chains can run Phase 2/3 simulations
3. ETH/BTC use correct propagation byte sizes (not gas/weight)
4. Chain configs have proper propagation overrides
"""

import pytest

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.core.phase2_engine import Phase2Engine, Phase2Config
from simulator.chains.base import get_chain_config, CHAIN_CONFIGS
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


class TestChainConfigs:
    """Test chain configuration correctness."""

    def test_all_chains_have_propagation_overhead(self):
        """All chains should define propagation_tx_overhead_bytes."""
        for name, cfg in CHAIN_CONFIGS.items():
            # Either explicit or fallback to base_tx_overhead
            effective = cfg.propagation_tx_overhead_bytes or cfg.base_tx_overhead
            assert effective > 0, f"{name} has no propagation overhead"

    def test_ethereum_propagation_overhead_is_bytes(self):
        """ETH propagation overhead should be ~120 bytes, not 21000 gas."""
        cfg = get_chain_config("ethereum")
        assert cfg.propagation_tx_overhead_bytes == 120
        assert cfg.base_tx_overhead == 21000  # Gas units for capacity

    def test_bitcoin_has_compact_block_routing(self):
        cfg = get_chain_config("bitcoin")
        assert cfg.routing_strategy == "compact_block"

    def test_solana_has_turbine_routing(self):
        cfg = get_chain_config("solana")
        assert cfg.routing_strategy == "turbine"

    def test_ethereum_has_hybrid_routing(self):
        cfg = get_chain_config("ethereum")
        assert cfg.routing_strategy == "eth_hybrid"


class TestPhase1MultiChain:
    """Test Phase 1 DES engine runs for all chains."""

    @pytest.mark.parametrize("chain,algo", [
        ("solana", "Ed25519"),
        ("bitcoin", "ECDSA"),
        ("ethereum", "ECDSA"),
    ])
    def test_phase1_runs_and_produces_blocks(self, chain, algo):
        """Each chain should produce at least 1 block in a basic run."""
        chain_cfg = get_chain_config(chain)
        # Duration: at least 2x block time to guarantee blocks
        duration = chain_cfg.block_time_ms * 3

        cfg = SimulationConfig(
            chain=chain,
            signature_algorithm=algo,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=duration,
            random_seed=42,
            nic_contention_enabled=True,
            use_chain_routing=True,
        )
        result = DESEngine(cfg).run()

        assert result.num_blocks >= 1, f"{chain} produced no blocks"
        assert result.avg_block_size_bytes > 0
        assert result.avg_propagation_p90_ms > 0

    @pytest.mark.parametrize("chain,algo", [
        ("solana", "ML-DSA-65"),
        ("bitcoin", "ML-DSA-65"),
        ("ethereum", "ML-DSA-65"),
    ])
    def test_phase1_pqc_runs(self, chain, algo):
        """Each chain should work with PQC algorithms."""
        chain_cfg = get_chain_config(chain)
        duration = chain_cfg.block_time_ms * 3

        cfg = SimulationConfig(
            chain=chain,
            signature_algorithm=algo,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=duration,
            random_seed=42,
        )
        result = DESEngine(cfg).run()
        assert result.num_blocks >= 1


class TestEthereumPropagationSize:
    """Ensure Ethereum blocks use byte sizes, not gas, for propagation."""

    def test_eth_block_size_is_bytes(self):
        """ETH block size should be reasonable bytes, not millions of gas."""
        cfg = SimulationConfig(
            chain="ethereum",
            signature_algorithm="ECDSA",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=36_000,  # 3 blocks
            random_seed=42,
        )
        result = DESEngine(cfg).run()

        # With ECDSA (72 sig + 33 pk + 120 overhead = 225 bytes/tx)
        # ETH gas limit 30M / (21000 + (225*16)) gas per tx ≈ ~1100 txs
        # 1100 * 225 bytes ≈ ~247 KB per block
        # Should be well under 1 MB, definitely not 30M
        assert result.avg_block_size_bytes < 5_000_000, \
            f"ETH block size {result.avg_block_size_bytes} looks like gas units, not bytes"
        assert result.avg_block_size_bytes > 10_000, \
            f"ETH block size {result.avg_block_size_bytes} too small"

    def test_eth_pqc_block_size_reasonable(self):
        """ETH PQC blocks should be larger but still in bytes."""
        cfg = SimulationConfig(
            chain="ethereum",
            signature_algorithm="ML-DSA-65",
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=36_000,
            random_seed=42,
        )
        result = DESEngine(cfg).run()

        # ML-DSA-65: 3309 sig + 1952 pk + 120 overhead = 5381 bytes/tx
        # Fewer txs fit in gas budget: 30M / (21000 + (5381*16)) ≈ ~270 txs
        # 270 * 5381 ≈ ~1.45 MB
        assert result.avg_block_size_bytes < 10_000_000
        assert result.avg_block_size_bytes > 100_000


class TestPhase2MultiChain:
    """Test Phase 2/3 engine with all chains."""

    def test_solana_phase2(self):
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.5,
            lambda_tps=4000.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2000,
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert result["num_blocks"] >= 1
        assert result["pqc_fraction"] == 0.5

    def test_bitcoin_phase2(self):
        """Bitcoin with its long block time should still work."""
        cfg = Phase2Config(
            chain="bitcoin",
            pqc_fraction=0.3,
            lambda_tps=7.0,
            classical_algo="ECDSA",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=1_200_000,  # 2 block times
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert result["num_blocks"] >= 1
        assert result["chain"] == "bitcoin"

    def test_ethereum_phase2(self):
        cfg = Phase2Config(
            chain="ethereum",
            pqc_fraction=0.5,
            lambda_tps=30.0,
            classical_algo="ECDSA",
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=48_000,  # 4 block times
            random_seed=42,
        )
        result = Phase2Engine(cfg).run()
        assert result["num_blocks"] >= 1
        assert result["chain"] == "ethereum"

    def test_phase2_nic_contention_flag(self):
        """Phase2Config should pass NIC contention flag through."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.5,
            lambda_tps=4000.0,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2000,
            random_seed=42,
            nic_contention_enabled=False,
        )
        result = Phase2Engine(cfg).run()
        assert result["num_blocks"] >= 1
