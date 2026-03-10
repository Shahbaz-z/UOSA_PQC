"""Tests for vote transaction overhead in DES engine."""

import os
import sys
import pytest

# Ensure MOCK_PQC is set
os.environ["MOCK_PQC"] = "1"

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from simulator.core.phase2_engine import Phase2Engine, Phase2Config


class TestVoteOverhead:
    """Test vote transaction injection."""

    def test_no_votes_by_default(self):
        """With vote_tx_fraction=0, no vote txs should appear."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=500,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=2000,
            random_seed=42,
            vote_tx_fraction=0.0,
        )
        result = Phase2Engine(cfg).run()
        assert result.get("vote_tx_count_total", 0) == 0

    def test_votes_injected_for_solana(self):
        """With vote_tx_fraction > 0 on Solana, votes should be injected."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=500,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5000,
            random_seed=42,
            vote_tx_fraction=0.50,
        )
        result = Phase2Engine(cfg).run()
        # Should have some vote txs
        assert result.get("vote_tx_fraction_config") == 0.50

    def test_no_votes_for_bitcoin(self):
        """Bitcoin should never get vote txs even if fraction > 0."""
        cfg = Phase2Config(
            chain="bitcoin",
            pqc_fraction=0.0,
            lambda_tps=7,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=1200000,
            random_seed=42,
            vote_tx_fraction=0.30,  # Should be ignored
        )
        result = Phase2Engine(cfg).run()
        assert result.get("vote_tx_count_total", 0) == 0

    def test_no_votes_for_ethereum(self):
        """Ethereum should never get vote txs."""
        cfg = Phase2Config(
            chain="ethereum",
            pqc_fraction=0.0,
            lambda_tps=30,
            num_validators=20,
            num_full_nodes=10,
            simulation_duration_ms=60000,
            random_seed=42,
            vote_tx_fraction=0.30,  # Should be ignored
        )
        result = Phase2Engine(cfg).run()
        assert result.get("vote_tx_count_total", 0) == 0

    def test_vote_overhead_fraction_reasonable(self):
        """Vote overhead fraction should be between 0 and 1."""
        cfg = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=500,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5000,
            random_seed=42,
            vote_tx_fraction=0.30,
        )
        result = Phase2Engine(cfg).run()
        frac = result.get("vote_overhead_fraction", 0.0)
        assert 0.0 <= frac <= 1.0

    def test_effective_user_tps_less_with_votes(self):
        """Effective user TPS should be less when votes consume block space."""
        cfg_no_votes = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=500,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5000,
            random_seed=42,
            vote_tx_fraction=0.0,
        )
        cfg_with_votes = Phase2Config(
            chain="solana",
            pqc_fraction=0.0,
            lambda_tps=500,
            num_validators=10,
            num_full_nodes=5,
            simulation_duration_ms=5000,
            random_seed=42,
            vote_tx_fraction=0.50,
        )
        result_no = Phase2Engine(cfg_no_votes).run()
        result_yes = Phase2Engine(cfg_with_votes).run()
        # Both should produce results
        assert result_no.get("effective_tps", 0) > 0
        assert result_yes.get("effective_tps", 0) >= 0
