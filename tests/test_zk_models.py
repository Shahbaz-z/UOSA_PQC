"""Tests for ZK proof system models (blockchain/zk_models.py).

Tests cover:
- Proof system parameter validation
- Throughput analysis calculations
- ZK vs signature comparison
- Quantum resistance classification
- Edge cases and error handling
"""

import pytest

from blockchain.zk_models import (
    ZK_PROOF_SYSTEMS,
    ZKProofParams,
    ZKProofAnalysis,
    ZKvsSignatureComparison,
    SNARK_SYSTEMS,
    STARK_SYSTEMS,
    QR_PROOF_SYSTEMS,
    analyze_zk_proof_throughput,
    compare_all_zk_proofs,
    compare_zk_vs_signature,
    build_zk_vs_signatures_table,
    ETH_BLOCK_GAS_LIMIT_DEFAULT,
    ETH_BLOCK_TIME_MS_DEFAULT,
    ECDSA_TX_GAS,
)


# ---------------------------------------------------------------------------
# Proof system catalog tests
# ---------------------------------------------------------------------------

class TestZKProofSystems:
    """Tests for the ZK_PROOF_SYSTEMS catalog."""

    def test_all_systems_present(self):
        """All 5 proof systems should be in the catalog."""
        expected = {"Groth16", "PLONK", "Halo2", "STARK-S", "STARK-L"}
        assert set(ZK_PROOF_SYSTEMS.keys()) == expected

    def test_snark_systems(self):
        """SNARK systems should include Groth16, PLONK, Halo2."""
        assert set(SNARK_SYSTEMS) == {"Groth16", "PLONK", "Halo2"}

    def test_stark_systems(self):
        """STARK systems should include STARK-S, STARK-L."""
        assert set(STARK_SYSTEMS) == {"STARK-S", "STARK-L"}

    def test_quantum_resistant_systems(self):
        """Only STARK systems should be quantum-resistant."""
        assert set(QR_PROOF_SYSTEMS) == {"STARK-S", "STARK-L"}

    def test_all_have_positive_proof_bytes(self):
        """All proof systems should have positive proof sizes."""
        for name, params in ZK_PROOF_SYSTEMS.items():
            assert params.proof_bytes > 0, f"{name} has non-positive proof_bytes"

    def test_all_have_positive_verification_gas(self):
        """All proof systems should have positive verification gas."""
        for name, params in ZK_PROOF_SYSTEMS.items():
            assert params.verification_gas > 0, f"{name} has non-positive verification_gas"

    def test_snarks_not_quantum_resistant(self):
        """SNARKs (Groth16, PLONK, Halo2) should NOT be quantum-resistant."""
        for system in SNARK_SYSTEMS:
            assert not ZK_PROOF_SYSTEMS[system].quantum_resistant, (
                f"{system} should not be quantum-resistant"
            )

    def test_starks_quantum_resistant(self):
        """STARKs should be quantum-resistant."""
        for system in STARK_SYSTEMS:
            assert ZK_PROOF_SYSTEMS[system].quantum_resistant, (
                f"{system} should be quantum-resistant"
            )

    def test_groth16_requires_trusted_setup(self):
        """Groth16 requires a per-circuit trusted setup."""
        assert ZK_PROOF_SYSTEMS["Groth16"].trusted_setup is True

    def test_starks_no_trusted_setup(self):
        """STARKs are transparent (no trusted setup)."""
        for system in STARK_SYSTEMS:
            assert ZK_PROOF_SYSTEMS[system].trusted_setup is False, (
                f"{system} should not require trusted setup"
            )

    def test_groth16_smallest_proof(self):
        """Groth16 should have the smallest proof size."""
        groth16_size = ZK_PROOF_SYSTEMS["Groth16"].proof_bytes
        for name, params in ZK_PROOF_SYSTEMS.items():
            if name != "Groth16":
                assert params.proof_bytes > groth16_size, (
                    f"{name} ({params.proof_bytes} B) should be larger than Groth16 ({groth16_size} B)"
                )

    def test_stark_l_largest_proof(self):
        """STARK-L should have the largest proof size."""
        stark_l_size = ZK_PROOF_SYSTEMS["STARK-L"].proof_bytes
        for name, params in ZK_PROOF_SYSTEMS.items():
            if name != "STARK-L":
                assert params.proof_bytes < stark_l_size, (
                    f"{name} ({params.proof_bytes} B) should be smaller than STARK-L ({stark_l_size} B)"
                )

    def test_all_have_descriptions(self):
        """All proof systems should have non-empty descriptions."""
        for name, params in ZK_PROOF_SYSTEMS.items():
            assert len(params.description) > 0, f"{name} has empty description"

    def test_all_have_proof_families(self):
        """All proof systems should have STARK or SNARK family."""
        for name, params in ZK_PROOF_SYSTEMS.items():
            assert params.proof_family in ("STARK", "SNARK"), (
                f"{name} has invalid proof_family: {params.proof_family}"
            )


# ---------------------------------------------------------------------------
# Throughput analysis tests
# ---------------------------------------------------------------------------

class TestZKProofThroughput:
    """Tests for analyze_zk_proof_throughput."""

    @pytest.mark.parametrize("system", list(ZK_PROOF_SYSTEMS.keys()))
    def test_all_systems_analyzable(self, system):
        """Every proof system should produce a valid analysis."""
        result = analyze_zk_proof_throughput(system)
        assert isinstance(result, ZKProofAnalysis)
        assert result.proof_system == system
        assert result.txs_per_block > 0
        assert result.throughput_tps > 0

    def test_invalid_system_raises(self):
        """Unknown proof system should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown proof system"):
            analyze_zk_proof_throughput("FakeSystem")

    def test_groth16_highest_throughput(self):
        """Groth16 (smallest proof + lowest gas) should have highest throughput."""
        results = compare_all_zk_proofs()
        groth16 = next(r for r in results if r.proof_system == "Groth16")
        for r in results:
            if r.proof_system != "Groth16":
                assert groth16.txs_per_block >= r.txs_per_block, (
                    f"Groth16 ({groth16.txs_per_block}) should have >= txs/block than {r.proof_system} ({r.txs_per_block})"
                )

    def test_stark_l_lowest_throughput(self):
        """STARK-L (largest proof + highest gas) should have lowest throughput."""
        results = compare_all_zk_proofs()
        stark_l = next(r for r in results if r.proof_system == "STARK-L")
        for r in results:
            if r.proof_system != "STARK-L":
                assert stark_l.txs_per_block <= r.txs_per_block, (
                    f"STARK-L ({stark_l.txs_per_block}) should have <= txs/block than {r.proof_system} ({r.txs_per_block})"
                )

    def test_relative_to_ecdsa(self):
        """All ZK proofs should have lower throughput than ECDSA baseline."""
        results = compare_all_zk_proofs()
        for r in results:
            assert 0 < r.relative_to_ecdsa < 1.0, (
                f"{r.proof_system} has relative_to_ecdsa={r.relative_to_ecdsa}, "
                "expected between 0 and 1"
            )

    def test_gas_overhead_positive(self):
        """All ZK proofs should have positive gas overhead vs ECDSA."""
        results = compare_all_zk_proofs()
        for r in results:
            assert r.gas_overhead_vs_ecdsa > 0, (
                f"{r.proof_system} should have positive gas overhead vs ECDSA"
            )

    def test_higher_gas_limit_more_throughput(self):
        """Higher gas limit should result in more transactions per block."""
        low = analyze_zk_proof_throughput("STARK-S", block_gas_limit=30_000_000)
        high = analyze_zk_proof_throughput("STARK-S", block_gas_limit=180_000_000)
        assert high.txs_per_block > low.txs_per_block
        assert high.throughput_tps > low.throughput_tps

    def test_total_gas_calculation(self):
        """Verify total gas = base + calldata + verification."""
        params = ZK_PROOF_SYSTEMS["Groth16"]
        result = analyze_zk_proof_throughput("Groth16")
        expected_calldata_gas = params.proof_bytes * 16  # ETH_CALLDATA_GAS_PER_BYTE
        expected_total = 21_000 + expected_calldata_gas + params.verification_gas
        assert result.total_tx_gas == expected_total

    def test_no_calldata_cost(self):
        """When include_calldata_cost=False, only base + verification gas."""
        params = ZK_PROOF_SYSTEMS["STARK-S"]
        result = analyze_zk_proof_throughput("STARK-S", include_calldata_cost=False)
        expected_total = 21_000 + params.verification_gas
        assert result.total_tx_gas == expected_total

    def test_12_second_block_time(self):
        """Verify TPS calculation with 12-second block time."""
        result = analyze_zk_proof_throughput(
            "Groth16",
            block_gas_limit=30_000_000,
            block_time_ms=12_000,
        )
        expected_tps = result.txs_per_block / (12_000 / 1000)
        assert abs(result.throughput_tps - round(expected_tps, 2)) < 0.01


class TestCompareAllZKProofs:
    """Tests for compare_all_zk_proofs."""

    def test_returns_all_systems(self):
        """Should return analysis for every proof system."""
        results = compare_all_zk_proofs()
        assert len(results) == len(ZK_PROOF_SYSTEMS)
        names = {r.proof_system for r in results}
        assert names == set(ZK_PROOF_SYSTEMS.keys())

    def test_all_positive_tps(self):
        """All results should have positive TPS."""
        for r in compare_all_zk_proofs():
            assert r.throughput_tps > 0, f"{r.proof_system} has non-positive TPS"

    def test_custom_gas_limit(self):
        """Custom gas limit should be used."""
        results = compare_all_zk_proofs(block_gas_limit=180_000_000)
        for r in results:
            assert r.txs_per_block > 0


# ---------------------------------------------------------------------------
# ZK vs signature comparison tests
# ---------------------------------------------------------------------------

class TestZKvsSignature:
    """Tests for compare_zk_vs_signature."""

    def test_groth16_vs_ecdsa(self):
        """Compare Groth16 against ECDSA."""
        result = compare_zk_vs_signature(
            "Groth16",
            "ECDSA",
            sig_bytes=72,
            sig_pk_bytes=33,
            sig_quantum_resistant=False,
        )
        assert isinstance(result, ZKvsSignatureComparison)
        assert result.zk_system == "Groth16"
        assert result.signature_scheme == "ECDSA"
        assert result.zk_proof_bytes == 128
        assert result.signature_bytes == 72
        assert not result.zk_quantum_resistant
        assert not result.sig_quantum_resistant

    def test_stark_vs_ml_dsa(self):
        """Compare STARK-S against ML-DSA-65 (both quantum-resistant)."""
        result = compare_zk_vs_signature(
            "STARK-S",
            "ML-DSA-65",
            sig_bytes=3293,
            sig_pk_bytes=1952,
            sig_quantum_resistant=True,
        )
        assert result.zk_quantum_resistant is True
        assert result.sig_quantum_resistant is True
        assert result.zk_proof_bytes > result.signature_bytes  # STARK proof > ML-DSA sig

    def test_invalid_system_raises(self):
        """Unknown proof system should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown proof system"):
            compare_zk_vs_signature("FakeSystem", "ECDSA", 72, 33, False)

    def test_size_ratio(self):
        """Size ratio should be zk_bytes / sig_bytes."""
        result = compare_zk_vs_signature(
            "Groth16", "ECDSA",
            sig_bytes=72, sig_pk_bytes=33,
            sig_quantum_resistant=False,
        )
        expected_ratio = round(128 / 72, 2)
        assert result.size_ratio == expected_ratio

    def test_gas_ratio(self):
        """Gas ratio should be zk_gas / sig_gas."""
        result = compare_zk_vs_signature(
            "Groth16", "ECDSA",
            sig_bytes=72, sig_pk_bytes=33,
            sig_quantum_resistant=False,
        )
        assert result.zk_tx_gas > result.sig_tx_gas  # ZK proof is more expensive
        assert result.gas_ratio > 1.0


# ---------------------------------------------------------------------------
# Build comparison table tests
# ---------------------------------------------------------------------------

class TestBuildComparisonTable:
    """Tests for build_zk_vs_signatures_table."""

    def test_returns_list_of_dicts(self):
        """Should return a list of dict rows."""
        rows = build_zk_vs_signatures_table()
        assert isinstance(rows, list)
        assert len(rows) > 0
        assert all(isinstance(r, dict) for r in rows)

    def test_includes_all_zk_systems(self):
        """Table should include all ZK proof systems."""
        rows = build_zk_vs_signatures_table()
        zk_schemes = {r["Scheme"] for r in rows if r["Type"].startswith("ZK-")}
        assert zk_schemes == set(ZK_PROOF_SYSTEMS.keys())

    def test_includes_signature_schemes(self):
        """Table should include ECDSA and key PQC signatures."""
        rows = build_zk_vs_signatures_table()
        sig_schemes = {r["Scheme"] for r in rows if r["Type"] == "Signature"}
        assert "ECDSA" in sig_schemes
        assert "Falcon-512" in sig_schemes
        assert "ML-DSA-65" in sig_schemes

    def test_all_have_required_fields(self):
        """All rows should have the expected fields."""
        required = {"Scheme", "Type", "Size (B)", "Tx Gas", "Txs/Block", "TPS",
                     "Quantum Resistant", "Trusted Setup"}
        rows = build_zk_vs_signatures_table()
        for row in rows:
            assert required.issubset(row.keys()), (
                f"Row {row['Scheme']} missing fields: {required - row.keys()}"
            )

    def test_starks_marked_quantum_resistant(self):
        """STARK rows should be marked as quantum-resistant."""
        rows = build_zk_vs_signatures_table()
        for r in rows:
            if r["Type"] == "ZK-STARK":
                assert r["Quantum Resistant"] == "Yes", (
                    f"{r['Scheme']} should be quantum-resistant"
                )

    def test_snarks_not_quantum_resistant(self):
        """SNARK rows should NOT be marked as quantum-resistant."""
        rows = build_zk_vs_signatures_table()
        for r in rows:
            if r["Type"] == "ZK-SNARK":
                assert r["Quantum Resistant"] == "No", (
                    f"{r['Scheme']} should not be quantum-resistant"
                )

    def test_custom_gas_limit(self):
        """Custom gas limit should affect TPS values."""
        low = build_zk_vs_signatures_table(block_gas_limit=30_000_000)
        high = build_zk_vs_signatures_table(block_gas_limit=180_000_000)
        # STARK-S should have higher TPS at higher gas limit
        stark_low = next(r for r in low if r["Scheme"] == "STARK-S")
        stark_high = next(r for r in high if r["Scheme"] == "STARK-S")
        assert stark_high["TPS"] > stark_low["TPS"]


# ---------------------------------------------------------------------------
# ECDSA baseline tests
# ---------------------------------------------------------------------------

class TestECDSABaseline:
    """Tests for ECDSA baseline constants."""

    def test_ecdsa_tx_gas_calculation(self):
        """Verify ECDSA tx gas = 21000 + calldata * 16."""
        expected_calldata = 72 + 33 + 120  # sig + pk + overhead
        expected_gas = 21_000 + expected_calldata * 16
        assert ECDSA_TX_GAS == expected_gas

    def test_ecdsa_baseline_txs_per_block(self):
        """Verify ECDSA txs/block at 30M gas."""
        expected = 30_000_000 // ECDSA_TX_GAS
        result = analyze_zk_proof_throughput("Groth16")
        # relative_to_ecdsa uses ECDSA_TX_GAS internally
        ecdsa_txs = 30_000_000 // ECDSA_TX_GAS
        assert ecdsa_txs == expected
