"""Tests for the Quantum Resistance (QR) scoring model (blockchain/qr_score.py).

Tests cover:
- Score weight validation
- Per-dimension scoring functions
- Composite scoring across all chains
- Letter grading thresholds
- Recommendation generation
- Edge cases
"""

import pytest

from blockchain.qr_score import (
    SCORE_WEIGHTS,
    MIGRATION_FEASIBILITY,
    ZK_READINESS,
    DimensionScore,
    ChainQRScore,
    score_chain,
    score_all_chains,
    _throughput_retention_score,
    _signature_size_score,
    _migration_feasibility_score,
    _zk_readiness_score,
    _algorithm_diversity_score,
    _letter_grade,
    _recommendation,
)


# ---------------------------------------------------------------------------
# Score weights tests
# ---------------------------------------------------------------------------

class TestScoreWeights:
    """Tests for SCORE_WEIGHTS configuration."""

    def test_weights_sum_to_one(self):
        """Weights must sum to exactly 1.0."""
        total = sum(SCORE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, not 1.0"

    def test_all_weights_positive(self):
        """All weights must be positive."""
        for key, val in SCORE_WEIGHTS.items():
            assert val > 0, f"Weight for {key} is not positive: {val}"

    def test_expected_dimensions(self):
        """Should have exactly 5 dimensions."""
        expected = {
            "throughput_retention",
            "signature_size",
            "migration_feasibility",
            "zk_readiness",
            "algorithm_diversity",
        }
        assert set(SCORE_WEIGHTS.keys()) == expected

    def test_throughput_highest_weight(self):
        """Throughput retention should have the highest weight."""
        max_key = max(SCORE_WEIGHTS, key=SCORE_WEIGHTS.get)
        assert max_key == "throughput_retention"


# ---------------------------------------------------------------------------
# Migration feasibility data tests
# ---------------------------------------------------------------------------

class TestMigrationFeasibility:
    """Tests for MIGRATION_FEASIBILITY data."""

    def test_all_chains_present(self):
        assert set(MIGRATION_FEASIBILITY.keys()) == {"Solana", "Bitcoin", "Ethereum"}

    def test_scores_in_range(self):
        for chain, info in MIGRATION_FEASIBILITY.items():
            assert 0 <= info["score"] <= 100, f"{chain} score out of range"

    def test_ethereum_highest_feasibility(self):
        """Ethereum should have highest migration feasibility (account abstraction)."""
        eth = MIGRATION_FEASIBILITY["Ethereum"]["score"]
        for chain, info in MIGRATION_FEASIBILITY.items():
            if chain != "Ethereum":
                assert eth >= info["score"], (
                    f"Ethereum ({eth}) should be >= {chain} ({info['score']})"
                )

    def test_bitcoin_lowest_feasibility(self):
        """Bitcoin should have lowest migration feasibility (conservative governance)."""
        btc = MIGRATION_FEASIBILITY["Bitcoin"]["score"]
        for chain, info in MIGRATION_FEASIBILITY.items():
            if chain != "Bitcoin":
                assert btc <= info["score"], (
                    f"Bitcoin ({btc}) should be <= {chain} ({info['score']})"
                )

    def test_all_have_rationale(self):
        for chain, info in MIGRATION_FEASIBILITY.items():
            assert len(info["rationale"]) > 0, f"{chain} has empty rationale"

    def test_hard_fork_fields(self):
        """Ethereum should not require hard fork; others should."""
        assert MIGRATION_FEASIBILITY["Ethereum"]["hard_fork_required"] is False
        assert MIGRATION_FEASIBILITY["Bitcoin"]["hard_fork_required"] is True
        assert MIGRATION_FEASIBILITY["Solana"]["hard_fork_required"] is True


# ---------------------------------------------------------------------------
# ZK readiness data tests
# ---------------------------------------------------------------------------

class TestZKReadiness:
    """Tests for ZK_READINESS data."""

    def test_all_chains_present(self):
        assert set(ZK_READINESS.keys()) == {"Solana", "Bitcoin", "Ethereum"}

    def test_scores_in_range(self):
        for chain, info in ZK_READINESS.items():
            assert 0 <= info["score"] <= 100, f"{chain} score out of range"

    def test_ethereum_highest_zk_readiness(self):
        """Ethereum should have highest ZK readiness (precompiles, rollups)."""
        eth = ZK_READINESS["Ethereum"]["score"]
        for chain, info in ZK_READINESS.items():
            if chain != "Ethereum":
                assert eth >= info["score"]

    def test_bitcoin_lowest_zk_readiness(self):
        """Bitcoin should have lowest ZK readiness (limited Script)."""
        btc = ZK_READINESS["Bitcoin"]["score"]
        for chain, info in ZK_READINESS.items():
            if chain != "Bitcoin":
                assert btc <= info["score"]

    def test_all_have_rationale(self):
        for chain, info in ZK_READINESS.items():
            assert len(info["rationale"]) > 0, f"{chain} has empty rationale"


# ---------------------------------------------------------------------------
# Dimension scoring function tests
# ---------------------------------------------------------------------------

class TestThroughputRetentionScore:
    """Tests for _throughput_retention_score."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_dimension_score(self, chain):
        result = _throughput_retention_score(chain)
        assert isinstance(result, DimensionScore)
        assert result.dimension == "throughput_retention"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_score_in_range(self, chain):
        result = _throughput_retention_score(chain)
        assert 0 <= result.score <= 100, f"{chain} score {result.score} out of range"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_weighted_score_correct(self, chain):
        result = _throughput_retention_score(chain)
        expected = round(result.score * SCORE_WEIGHTS["throughput_retention"], 2)
        assert abs(result.weighted_score - expected) < 0.01

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_has_detail(self, chain):
        result = _throughput_retention_score(chain)
        assert len(result.detail) > 0


class TestSignatureSizeScore:
    """Tests for _signature_size_score."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_dimension_score(self, chain):
        result = _signature_size_score(chain)
        assert isinstance(result, DimensionScore)
        assert result.dimension == "signature_size"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_score_in_range(self, chain):
        result = _signature_size_score(chain)
        assert 0 <= result.score <= 100

    def test_solana_vs_bitcoin_different_baseline(self):
        """Solana (Ed25519=64B) should have different score than Bitcoin (ECDSA=72B)."""
        sol = _signature_size_score("Solana")
        btc = _signature_size_score("Bitcoin")
        # Solana has smaller classical sig, so larger ratio to Falcon, lower score
        assert sol.score != btc.score


class TestMigrationFeasibilityScore:
    """Tests for _migration_feasibility_score."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_dimension_score(self, chain):
        result = _migration_feasibility_score(chain)
        assert isinstance(result, DimensionScore)
        assert result.dimension == "migration_feasibility"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_matches_config(self, chain):
        result = _migration_feasibility_score(chain)
        assert result.score == MIGRATION_FEASIBILITY[chain]["score"]


class TestZKReadinessScore:
    """Tests for _zk_readiness_score."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_dimension_score(self, chain):
        result = _zk_readiness_score(chain)
        assert isinstance(result, DimensionScore)
        assert result.dimension == "zk_readiness"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_matches_config(self, chain):
        result = _zk_readiness_score(chain)
        assert result.score == ZK_READINESS[chain]["score"]


class TestAlgorithmDiversityScore:
    """Tests for _algorithm_diversity_score."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_dimension_score(self, chain):
        result = _algorithm_diversity_score(chain)
        assert isinstance(result, DimensionScore)
        assert result.dimension == "algorithm_diversity"

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_score_in_range(self, chain):
        result = _algorithm_diversity_score(chain)
        assert 0 <= result.score <= 100

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_score_is_multiple_of_33(self, chain):
        """Score should be 33 per viable family (0, 33, 66, 99)."""
        result = _algorithm_diversity_score(chain)
        assert result.score % 33 == 0

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_at_least_one_family(self, chain):
        """Every chain should have at least one viable PQC family."""
        result = _algorithm_diversity_score(chain)
        assert result.score >= 33

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_hybrid_not_counted_as_separate_family(self, chain):
        """Hybrid schemes should not inflate the family count."""
        result = _algorithm_diversity_score(chain)
        # Should never mention 'Hybrid' as a standalone family
        assert "Hybrid" not in result.detail


# ---------------------------------------------------------------------------
# Letter grade tests
# ---------------------------------------------------------------------------

class TestLetterGrade:
    """Tests for _letter_grade."""

    def test_grade_a(self):
        assert _letter_grade(85) == "A"
        assert _letter_grade(100) == "A"
        assert _letter_grade(90) == "A"

    def test_grade_b(self):
        assert _letter_grade(75) == "B"
        assert _letter_grade(80) == "B"
        assert _letter_grade(84.9) == "B"

    def test_grade_c(self):
        assert _letter_grade(60) == "C"
        assert _letter_grade(70) == "C"
        assert _letter_grade(74.9) == "C"

    def test_grade_d(self):
        assert _letter_grade(45) == "D"
        assert _letter_grade(55) == "D"
        assert _letter_grade(59.9) == "D"

    def test_grade_f(self):
        assert _letter_grade(0) == "F"
        assert _letter_grade(30) == "F"
        assert _letter_grade(44.9) == "F"

    def test_boundary_exact(self):
        """Exact boundary values should get the higher grade."""
        assert _letter_grade(85.0) == "A"
        assert _letter_grade(75.0) == "B"
        assert _letter_grade(60.0) == "C"
        assert _letter_grade(45.0) == "D"


# ---------------------------------------------------------------------------
# Recommendation tests
# ---------------------------------------------------------------------------

class TestRecommendation:
    """Tests for _recommendation."""

    def test_high_score_recommendation(self):
        rec = _recommendation("Ethereum", 80, "Falcon-512")
        assert "strong" in rec.lower()
        assert "Falcon-512" in rec
        assert "Ethereum" in rec

    def test_moderate_score_recommendation(self):
        rec = _recommendation("Solana", 60, "Falcon-512")
        assert "moderate" in rec.lower()
        assert "Falcon-512" in rec

    def test_low_score_recommendation(self):
        rec = _recommendation("Bitcoin", 40, "Falcon-512")
        assert "challenge" in rec.lower() or "significant" in rec.lower()
        assert "Falcon-512" in rec


# ---------------------------------------------------------------------------
# Composite scoring tests
# ---------------------------------------------------------------------------

class TestScoreChain:
    """Tests for score_chain."""

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_returns_chain_qr_score(self, chain):
        result = score_chain(chain)
        assert isinstance(result, ChainQRScore)
        assert result.chain == chain

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_has_five_dimensions(self, chain):
        result = score_chain(chain)
        assert len(result.dimensions) == 5

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_composite_score_in_range(self, chain):
        result = score_chain(chain)
        assert 0 <= result.composite_score <= 100

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_composite_equals_sum_of_weighted(self, chain):
        result = score_chain(chain)
        expected = sum(d.weighted_score for d in result.dimensions)
        assert abs(result.composite_score - round(expected, 1)) < 0.2

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_has_valid_grade(self, chain):
        result = score_chain(chain)
        assert result.grade in ("A", "B", "C", "D", "F")

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_grade_matches_score(self, chain):
        result = score_chain(chain)
        assert result.grade == _letter_grade(result.composite_score)

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_has_best_pqc_algorithm(self, chain):
        result = score_chain(chain)
        assert len(result.best_pqc_algorithm) > 0

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_best_pqc_retention_positive(self, chain):
        result = score_chain(chain)
        assert result.best_pqc_retention > 0

    @pytest.mark.parametrize("chain", ["Solana", "Bitcoin", "Ethereum"])
    def test_has_recommendation(self, chain):
        result = score_chain(chain)
        assert len(result.recommendation) > 0

    def test_invalid_chain_raises(self):
        with pytest.raises(ValueError, match="Unknown chain"):
            score_chain("Cardano")


class TestScoreAllChains:
    """Tests for score_all_chains."""

    def test_returns_three_scores(self):
        results = score_all_chains()
        assert len(results) == 3

    def test_correct_chain_order(self):
        results = score_all_chains()
        chains = [r.chain for r in results]
        assert chains == ["Solana", "Bitcoin", "Ethereum"]

    def test_all_have_grades(self):
        results = score_all_chains()
        for r in results:
            assert r.grade in ("A", "B", "C", "D", "F")


# ---------------------------------------------------------------------------
# Cross-chain comparison tests (sanity checks on relative rankings)
# ---------------------------------------------------------------------------

class TestCrossChainRankings:
    """Sanity checks on relative chain rankings."""

    def test_ethereum_highest_composite(self):
        """Ethereum should have the highest composite score (best migration + ZK)."""
        results = score_all_chains()
        eth = next(r for r in results if r.chain == "Ethereum")
        for r in results:
            if r.chain != "Ethereum":
                assert eth.composite_score >= r.composite_score, (
                    f"Ethereum ({eth.composite_score}) should be >= {r.chain} ({r.composite_score})"
                )

    def test_bitcoin_lowest_composite(self):
        """Bitcoin should have the lowest composite score (UTXO + low ZK + slow governance)."""
        results = score_all_chains()
        btc = next(r for r in results if r.chain == "Bitcoin")
        for r in results:
            if r.chain != "Bitcoin":
                assert btc.composite_score <= r.composite_score, (
                    f"Bitcoin ({btc.composite_score}) should be <= {r.chain} ({r.composite_score})"
                )

    def test_all_chains_above_30(self):
        """No chain should score below 30 (all have at least some PQC viability)."""
        results = score_all_chains()
        for r in results:
            assert r.composite_score > 30, f"{r.chain} scored {r.composite_score}"
