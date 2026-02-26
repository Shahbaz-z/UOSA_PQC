"""Tests for blockchain/aggregation.py -- signature aggregation models."""

import pytest

from blockchain.aggregation import (
    AGGREGATION_SCHEMES,
    AggregationScheme,
    AggregationAnalysis,
    get_aggregation_scheme,
    analyze_aggregation,
    compare_aggregation_schemes,
)
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES


# ---------------------------------------------------------------------------
# Scheme catalog tests
# ---------------------------------------------------------------------------

class TestAggregationSchemes:
    def test_none_scheme_exists(self):
        assert "None" in AGGREGATION_SCHEMES

    def test_bls_scheme_exists(self):
        assert "BLS" in AGGREGATION_SCHEMES

    def test_falcon_tree_scheme_exists(self):
        assert "Falcon-Tree" in AGGREGATION_SCHEMES

    def test_mldsa_batch_scheme_exists(self):
        assert "ML-DSA-Batch" in AGGREGATION_SCHEMES

    def test_bls_not_quantum_resistant(self):
        assert AGGREGATION_SCHEMES["BLS"].quantum_resistant is False

    def test_falcon_tree_quantum_resistant(self):
        assert AGGREGATION_SCHEMES["Falcon-Tree"].quantum_resistant is True

    def test_mldsa_batch_quantum_resistant(self):
        assert AGGREGATION_SCHEMES["ML-DSA-Batch"].quantum_resistant is True

    def test_none_supports_all(self):
        scheme = AGGREGATION_SCHEMES["None"]
        for algo in SIGNATURE_SIZES:
            assert scheme.supports(algo)


# ---------------------------------------------------------------------------
# get_aggregation_scheme tests
# ---------------------------------------------------------------------------

class TestGetAggregationScheme:
    def test_valid(self):
        scheme = get_aggregation_scheme("BLS")
        assert isinstance(scheme, AggregationScheme)

    def test_invalid(self):
        with pytest.raises(ValueError, match="Unknown aggregation"):
            get_aggregation_scheme("FakeScheme")


# ---------------------------------------------------------------------------
# No aggregation (baseline)
# ---------------------------------------------------------------------------

class TestNoAggregation:
    def test_no_reduction(self):
        """Without aggregation, total = individual * batch_size."""
        result = analyze_aggregation("Falcon-512", "None", batch_size=100)
        assert result.aggregated_sig_bytes == SIGNATURE_SIZES["Falcon-512"] * 100
        assert result.aggregated_pk_bytes == PUBLIC_KEY_SIZES["Falcon-512"] * 100

    def test_amortized_equals_individual(self):
        result = analyze_aggregation("ML-DSA-65", "None", batch_size=50)
        assert result.amortized_sig_per_tx == SIGNATURE_SIZES["ML-DSA-65"]
        assert result.amortized_pk_per_tx == PUBLIC_KEY_SIZES["ML-DSA-65"]

    def test_zero_reduction(self):
        result = analyze_aggregation("Ed25519", "None", batch_size=10)
        assert result.size_reduction_pct == 0.0


# ---------------------------------------------------------------------------
# BLS aggregation
# ---------------------------------------------------------------------------

class TestBLSAggregation:
    def test_constant_sig_size(self):
        """BLS aggregate signature is always 48 bytes."""
        result = analyze_aggregation("BLS12-381", "BLS", batch_size=100)
        assert result.aggregated_sig_bytes == 48

    def test_constant_sig_size_any_batch(self):
        r1 = analyze_aggregation("BLS12-381", "BLS", batch_size=1)
        r100 = analyze_aggregation("BLS12-381", "BLS", batch_size=100)
        r1000 = analyze_aggregation("BLS12-381", "BLS", batch_size=1000)
        assert r1.aggregated_sig_bytes == r100.aggregated_sig_bytes == r1000.aggregated_sig_bytes == 48

    def test_pk_scales_linearly(self):
        """BLS PKs are per-signer (48 bytes each)."""
        result = analyze_aggregation("BLS12-381", "BLS", batch_size=100)
        assert result.aggregated_pk_bytes == 48 * 100

    def test_not_quantum_resistant(self):
        result = analyze_aggregation("BLS12-381", "BLS", batch_size=10)
        assert result.quantum_resistant is False

    def test_unsupported_algorithm_raises(self):
        with pytest.raises(ValueError, match="does not support"):
            analyze_aggregation("Falcon-512", "BLS", batch_size=10)


# ---------------------------------------------------------------------------
# Falcon Merkle Tree aggregation
# ---------------------------------------------------------------------------

class TestFalconTreeAggregation:
    def test_single_sig_no_overhead(self):
        """With batch_size=1, Merkle tree adds no overhead."""
        result = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=1)
        assert result.aggregated_sig_bytes == SIGNATURE_SIZES["Falcon-512"]

    def test_logarithmic_growth(self):
        """Signature size grows logarithmically with batch size."""
        r10 = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=10)
        r100 = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=100)
        r1000 = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=1000)

        # log2(10) ~= 4, log2(100) ~= 7, log2(1000) ~= 10
        # Each step adds ~3 * 32 = 96 bytes
        assert r100.aggregated_sig_bytes > r10.aggregated_sig_bytes
        assert r1000.aggregated_sig_bytes > r100.aggregated_sig_bytes
        # But growth should be sub-linear
        assert (r1000.aggregated_sig_bytes - r10.aggregated_sig_bytes) < SIGNATURE_SIZES["Falcon-512"]

    def test_pk_is_merkle_root(self):
        """Public key is just a 32-byte Merkle root."""
        result = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=100)
        assert result.aggregated_pk_bytes == 32

    def test_significant_reduction(self):
        """At batch_size=100, should see major size reduction vs no aggregation."""
        result = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=100)
        assert result.size_reduction_pct > 90  # >90% reduction

    def test_quantum_resistant(self):
        result = analyze_aggregation("Falcon-512", "Falcon-Tree", batch_size=10)
        assert result.quantum_resistant is True

    def test_falcon_1024_supported(self):
        result = analyze_aggregation("Falcon-1024", "Falcon-Tree", batch_size=10)
        assert result.aggregated_sig_bytes > 0

    def test_mldsa_not_supported(self):
        with pytest.raises(ValueError, match="does not support"):
            analyze_aggregation("ML-DSA-65", "Falcon-Tree", batch_size=10)


# ---------------------------------------------------------------------------
# ML-DSA Batch verification
# ---------------------------------------------------------------------------

class TestMLDSABatch:
    def test_no_size_reduction(self):
        """ML-DSA batch has no size reduction."""
        result = analyze_aggregation("ML-DSA-65", "ML-DSA-Batch", batch_size=100)
        assert result.aggregated_sig_bytes == SIGNATURE_SIZES["ML-DSA-65"] * 100
        assert result.size_reduction_pct == 0.0

    def test_faster_verification(self):
        """Verification should be faster (factor < 1.0)."""
        result = analyze_aggregation("ML-DSA-65", "ML-DSA-Batch", batch_size=100)
        assert result.verification_time_factor < 1.0

    def test_all_mldsa_variants_supported(self):
        for algo in ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]:
            result = analyze_aggregation(algo, "ML-DSA-Batch", batch_size=10)
            assert result.algorithm == algo

    def test_falcon_not_supported(self):
        with pytest.raises(ValueError, match="does not support"):
            analyze_aggregation("Falcon-512", "ML-DSA-Batch", batch_size=10)


# ---------------------------------------------------------------------------
# analyze_aggregation general tests
# ---------------------------------------------------------------------------

class TestAnalyzeAggregation:
    def test_invalid_batch_size(self):
        with pytest.raises(ValueError, match="batch_size"):
            analyze_aggregation("Ed25519", "None", batch_size=0)

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError, match="Unknown algorithm"):
            analyze_aggregation("FakeAlgo", "None", batch_size=10)

    def test_result_structure(self):
        result = analyze_aggregation("Falcon-512", "None", batch_size=10)
        assert isinstance(result, AggregationAnalysis)
        assert result.batch_size == 10
        assert result.algorithm == "Falcon-512"
        assert result.scheme_name == "None"

    def test_ed25519_not_quantum_resistant(self):
        result = analyze_aggregation("Ed25519", "None", batch_size=10)
        assert result.quantum_resistant is False

    def test_falcon_quantum_resistant_with_none_scheme(self):
        result = analyze_aggregation("Falcon-512", "None", batch_size=10)
        assert result.quantum_resistant is True


# ---------------------------------------------------------------------------
# compare_aggregation_schemes tests
# ---------------------------------------------------------------------------

class TestCompareAggregationSchemes:
    def test_falcon_gets_two_schemes(self):
        """Falcon-512 should be compatible with None and Falcon-Tree."""
        results = compare_aggregation_schemes("Falcon-512", batch_size=50)
        scheme_names = [r.scheme_name for r in results]
        assert "None" in scheme_names
        assert "Falcon-Tree" in scheme_names
        assert len(results) == 2

    def test_mldsa_gets_two_schemes(self):
        """ML-DSA-65 should be compatible with None and ML-DSA-Batch."""
        results = compare_aggregation_schemes("ML-DSA-65", batch_size=50)
        scheme_names = [r.scheme_name for r in results]
        assert "None" in scheme_names
        assert "ML-DSA-Batch" in scheme_names
        assert len(results) == 2

    def test_ed25519_only_none(self):
        """Ed25519 has no PQC aggregation, just None."""
        results = compare_aggregation_schemes("Ed25519", batch_size=50)
        scheme_names = [r.scheme_name for r in results]
        assert scheme_names == ["None"]

    def test_all_results_have_same_algorithm(self):
        results = compare_aggregation_schemes("Falcon-512", batch_size=50)
        for r in results:
            assert r.algorithm == "Falcon-512"
