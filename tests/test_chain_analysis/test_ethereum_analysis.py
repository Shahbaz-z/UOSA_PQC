"""Tests for Ethereum PQC impact analysis."""

import pytest

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    ECDSA,
    FALCON_512,
    FALCON_1024,
    DILITHIUM2,
    DILITHIUM3,
    DILITHIUM5,
    SPHINCS_128S,
    SPHINCS_256S,
)
from analysis.ethereum_pqc_analysis import (
    GAS_LIMIT,
    BLOCK_TIME_S,
    CURRENT_ATTESTATION_BYTES,
    COMMITTEE_SIZE,
    TYPICAL_BANDWIDTH_MBPS,
    run_gas_cost_analysis,
    run_eip1559_analysis,
    simulate_eip1559,
    run_consensus_analysis,
    run_validator_economics,
    run_full_ethereum_analysis,
    _calldata_gas,
    _sig_overhead_gas,
)


# ── Helper function tests ─────────────────────────────────────────

class TestHelpers:
    def test_calldata_gas_positive(self):
        assert _calldata_gas(100) > 0

    def test_calldata_gas_scales(self):
        g1 = _calldata_gas(100)
        g2 = _calldata_gas(1000)
        assert g2 > g1

    def test_calldata_gas_zero_bytes(self):
        """Zero-length data costs 0 gas."""
        assert _calldata_gas(0) == 0

    def test_sig_overhead_positive_for_pqc(self):
        """PQC algorithms should have positive gas overhead vs ECDSA."""
        for alg in [FALCON_512, DILITHIUM2, SPHINCS_128S]:
            overhead = _sig_overhead_gas(alg)
            assert overhead > 0, f"{alg.name} should have positive overhead"


# ── Gas cost analysis ──────────────────────────────────────────────

class TestGasCostAnalysis:
    def test_returns_all_algorithms(self):
        results = run_gas_cost_analysis()
        assert len(results) == len(ALL_ALGORITHMS)

    def test_ecdsa_baseline_tps_reasonable(self):
        """ECDSA simple transfer TPS should be ~80-150."""
        results = run_gas_cost_analysis()
        ecdsa = results[0]
        assert ecdsa.algorithm == ECDSA.name
        assert 50 <= ecdsa.simple_tps <= 200, f"ECDSA TPS = {ecdsa.simple_tps}"

    def test_ecdsa_no_overhead(self):
        results = run_gas_cost_analysis()
        ecdsa = results[0]
        assert ecdsa.total_overhead_gas == 0

    def test_pqc_reduces_tps(self):
        results = run_gas_cost_analysis()
        ecdsa_tps = results[0].simple_tps
        for r in results[1:]:
            assert r.simple_tps < ecdsa_tps, f"{r.algorithm} TPS should be less than ECDSA"

    def test_erc20_less_than_simple(self):
        """ERC-20 transfers cost more gas → fewer per block."""
        results = run_gas_cost_analysis()
        for r in results:
            assert r.erc20_tps < r.simple_tps

    def test_complex_less_than_erc20(self):
        results = run_gas_cost_analysis()
        for r in results:
            assert r.complex_tps < r.erc20_tps

    def test_throughput_reduction_bounded(self):
        results = run_gas_cost_analysis()
        for r in results:
            assert 0.0 <= r.throughput_reduction_simple_pct <= 100.0

    def test_sig_gas_fraction_bounded(self):
        results = run_gas_cost_analysis()
        for r in results:
            assert 0.0 <= r.sig_gas_fraction <= 1.0

    def test_sphincs_highest_reduction(self):
        results = run_gas_cost_analysis()
        by_name = {r.algorithm: r for r in results}
        assert by_name[SPHINCS_256S.name].throughput_reduction_simple_pct > 90.0


# ── EIP-1559 simulation ───────────────────────────────────────────

class TestEIP1559:
    def test_basic_run(self):
        result = simulate_eip1559(ECDSA)
        assert result.equilibrium_base_fee_gwei > 0
        assert result.avg_block_utilization > 0

    def test_baseline_low_utilization(self):
        """At 150 txs/block with ECDSA, utilization should be well below 50%."""
        result = simulate_eip1559(ECDSA, demand_txs_per_block=150)
        assert result.avg_block_utilization < 0.5

    def test_pqc_higher_utilization(self):
        """PQC algorithms should drive higher block utilization."""
        r_ecdsa = simulate_eip1559(ECDSA, demand_txs_per_block=150)
        r_dil3 = simulate_eip1559(DILITHIUM3, demand_txs_per_block=150)
        assert r_dil3.avg_block_utilization > r_ecdsa.avg_block_utilization

    def test_full_analysis_multipliers(self):
        """First algorithm should have multiplier 1.0."""
        results = run_eip1559_analysis()
        assert results[0].base_fee_multiplier == 1.0

    def test_base_fee_bounded(self):
        """Base fee should not explode to unreasonable values."""
        results = run_eip1559_analysis()
        for r in results:
            assert r.equilibrium_base_fee_gwei <= 1_000_001  # Max cap + margin


# ── Consensus layer ───────────────────────────────────────────────

class TestConsensusLayer:
    def test_returns_all_algorithms(self):
        results = run_consensus_analysis()
        assert len(results) == len(ALL_ALGORITHMS)

    def test_ecdsa_baseline_feasible(self):
        results = run_consensus_analysis()
        ecdsa = results[0]
        assert ecdsa.slot_timing_feasible

    def test_falcon_512_feasible(self):
        """FALCON-512 should be feasible at 100 Mbps."""
        results = run_consensus_analysis()
        by_name = {r.algorithm: r for r in results}
        assert by_name[FALCON_512.name].slot_timing_feasible

    def test_dilithium_infeasible(self):
        """Dilithium2+ should be infeasible at 100 Mbps."""
        results = run_consensus_analysis()
        by_name = {r.algorithm: r for r in results}
        assert not by_name[DILITHIUM2.name].slot_timing_feasible

    def test_attestation_multiplier_increases(self):
        results = run_consensus_analysis()
        multipliers = [(r.algorithm, r.attestation_multiplier) for r in results]
        # FALCON-512 mult should be < DILITHIUM5 mult
        by_name = {r.algorithm: r for r in results}
        assert by_name[FALCON_512.name].attestation_multiplier < by_name[DILITHIUM5.name].attestation_multiplier

    def test_ecdsa_no_overhead(self):
        results = run_consensus_analysis()
        ecdsa = results[0]
        assert ecdsa.beacon_block_overhead_kb == 0.0


# ── Validator economics ───────────────────────────────────────────

class TestValidatorEconomics:
    def test_returns_all_algorithms(self):
        results = run_validator_economics()
        assert len(results) == len(ALL_ALGORITHMS)

    def test_ecdsa_baseline_zero_overhead(self):
        results = run_validator_economics()
        ecdsa = results[0]
        assert ecdsa.extra_bandwidth_gb_per_month == 0.0

    def test_pqc_positive_overhead(self):
        results = run_validator_economics()
        for r in results[1:]:
            assert r.extra_bandwidth_gb_per_month > 0, f"{r.algorithm} should have positive BW overhead"

    def test_centralization_risk_for_large_sigs(self):
        """Larger PQC sigs should push more validators below requirements."""
        results = run_validator_economics()
        by_name = {r.algorithm: r for r in results}
        assert by_name[SPHINCS_256S.name].pct_validators_below_requirement >= \
               by_name[FALCON_512.name].pct_validators_below_requirement


# ── Full analysis ─────────────────────────────────────────────────

class TestFullEthereumAnalysis:
    def test_runs_and_returns_all_components(self):
        results = run_full_ethereum_analysis()
        assert len(results.gas_cost) == len(ALL_ALGORITHMS)
        assert len(results.eip1559) == len(ALL_ALGORITHMS)
        assert len(results.consensus) == len(ALL_ALGORITHMS)
        assert len(results.validator_economics) == len(ALL_ALGORITHMS)
