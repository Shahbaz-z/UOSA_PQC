"""Tests for simulator/economics/tx_viability.py.

Covers:
- compute_tx_type_viability(): return type, viability logic, fee computation
- TxTypeViability: is_viable flag, breakeven_value, fee_multiplier_vs_classical
- ChainViabilityReport: viable_types, unviable_types, viability_fraction, summary_table
- viability_sweep(): all-algo sweep, multiplier comparison
- Edge cases: zero fee rate, unknown chain, very large fee rate
"""

from __future__ import annotations

import math
import pytest

from simulator.economics.tx_viability import (
    ChainViabilityReport,
    MAX_FEE_FRACTION,
    TYPICAL_TX_VALUES_USD,
    TxTypeViability,
    compute_tx_type_viability,
    viability_sweep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bitcoin_report(fee_rate: float = 1.0, algo: str = "ECDSA") -> ChainViabilityReport:
    return compute_tx_type_viability(
        chain="bitcoin",
        sig_algorithm=algo,
        base_fee_rate=fee_rate,
        native_asset_usd_price=60_000.0,
    )


def _ethereum_report(fee_rate: float = 20.0, algo: str = "ECDSA") -> ChainViabilityReport:
    return compute_tx_type_viability(
        chain="ethereum",
        sig_algorithm=algo,
        base_fee_rate=fee_rate,
        native_asset_usd_price=3_000.0,
    )


def _solana_report(fee_rate: float = 0.01, algo: str = "Ed25519") -> ChainViabilityReport:
    return compute_tx_type_viability(
        chain="solana",
        sig_algorithm=algo,
        base_fee_rate=fee_rate,
        native_asset_usd_price=150.0,
    )


# ---------------------------------------------------------------------------
# Section 1: Return-type and structural correctness
# ---------------------------------------------------------------------------

class TestReturnTypes:
    def test_returns_chain_viability_report(self):
        report = _bitcoin_report()
        assert isinstance(report, ChainViabilityReport)

    def test_report_has_results_dict(self):
        report = _bitcoin_report()
        assert isinstance(report.results, dict)
        assert len(report.results) > 0

    def test_results_are_tx_type_viability(self):
        report = _bitcoin_report()
        for tx_type, v in report.results.items():
            assert isinstance(v, TxTypeViability), f"{tx_type} should be TxTypeViability"

    def test_all_bitcoin_tx_types_present(self):
        report = _bitcoin_report()
        expected = set(TYPICAL_TX_VALUES_USD["bitcoin"])
        assert expected <= set(report.results.keys())

    def test_all_ethereum_tx_types_present(self):
        report = _ethereum_report()
        expected = set(TYPICAL_TX_VALUES_USD["ethereum"])
        assert expected <= set(report.results.keys())

    def test_all_solana_tx_types_present(self):
        report = _solana_report()
        expected = set(TYPICAL_TX_VALUES_USD["solana"])
        assert expected <= set(report.results.keys())

    def test_report_chain_field(self):
        report = _bitcoin_report()
        assert report.chain == "bitcoin"

    def test_report_sig_algorithm_field(self):
        report = _bitcoin_report(algo="Falcon-512")
        assert report.sig_algorithm == "Falcon-512"

    def test_report_base_fee_rate_field(self):
        report = _bitcoin_report(fee_rate=5.0)
        assert report.base_fee_rate == 5.0


# ---------------------------------------------------------------------------
# Section 2: TxTypeViability field correctness
# ---------------------------------------------------------------------------

class TestTxTypeViabilityFields:
    def test_is_viable_boolean(self):
        report = _bitcoin_report()
        for v in report.results.values():
            assert isinstance(v.is_viable, bool)

    def test_fee_fraction_non_negative(self):
        report = _bitcoin_report(fee_rate=1.0)
        for v in report.results.values():
            assert v.fee_fraction >= 0.0

    def test_estimated_fee_positive(self):
        report = _bitcoin_report(fee_rate=1.0)
        for v in report.results.values():
            assert v.estimated_fee_usd > 0.0

    def test_breakeven_value_positive(self):
        report = _bitcoin_report(fee_rate=1.0)
        for v in report.results.values():
            assert v.breakeven_value_usd > 0.0

    def test_is_viable_consistent_with_fee_vs_max(self):
        """is_viable should equal (estimated_fee <= max_fee_usd)."""
        report = _bitcoin_report(fee_rate=10.0)
        for v in report.results.values():
            expected = v.estimated_fee_usd <= v.max_fee_usd
            assert v.is_viable == expected, (
                f"{v.tx_type}: is_viable={v.is_viable} but "
                f"estimated={v.estimated_fee_usd:.6f} vs max={v.max_fee_usd:.6f}"
            )

    def test_max_fee_usd_consistent_with_fraction(self):
        """max_fee_usd == typical_value_usd × MAX_FEE_FRACTION[tx_type]."""
        report = _bitcoin_report(fee_rate=1.0)
        for tx_type, v in report.results.items():
            frac = MAX_FEE_FRACTION.get(tx_type, 0.02)
            expected_max = v.typical_value_usd * frac
            assert abs(v.max_fee_usd - expected_max) < 1e-9, (
                f"{tx_type}: max_fee_usd={v.max_fee_usd} vs expected={expected_max}"
            )

    def test_fee_fraction_equals_fee_over_value(self):
        """fee_fraction == estimated_fee_usd / typical_value_usd."""
        report = _bitcoin_report(fee_rate=1.0)
        for v in report.results.values():
            expected = v.estimated_fee_usd / v.typical_value_usd
            assert abs(v.fee_fraction - expected) < 1e-12

    def test_breakeven_value_satisfies_constraint(self):
        """At breakeven, fee / breakeven_value == max_fee_fraction."""
        report = _bitcoin_report(fee_rate=5.0)
        for tx_type, v in report.results.items():
            if math.isinf(v.breakeven_value_usd):
                continue
            frac = MAX_FEE_FRACTION.get(tx_type, 0.02)
            ratio = v.estimated_fee_usd / v.breakeven_value_usd
            assert abs(ratio - frac) < 1e-10, (
                f"{tx_type}: ratio={ratio:.8f} vs frac={frac}"
            )

    def test_tx_size_bytes_positive(self):
        report = _bitcoin_report()
        for v in report.results.values():
            assert v.tx_size_bytes > 0

    def test_typical_value_correct(self):
        """typical_value_usd should match TYPICAL_TX_VALUES_USD."""
        report = _bitcoin_report()
        for tx_type, v in report.results.items():
            expected = TYPICAL_TX_VALUES_USD["bitcoin"][tx_type]
            assert v.typical_value_usd == expected


# ---------------------------------------------------------------------------
# Section 3: Viability logic — classical should be viable at low fee rates
# ---------------------------------------------------------------------------

class TestViabilityLogic:
    def test_classical_btc_viable_at_low_fees(self):
        """ECDSA at 1 sat/vbyte should keep most tx types viable."""
        report = _bitcoin_report(fee_rate=1.0, algo="ECDSA")
        viable = report.viable_types
        # At 1 sat/vbyte, at minimum medium_transfer/whale_transfer should be viable
        assert len(viable) >= 2, f"Expected ≥2 viable at 1 sat/vbyte, got {viable}"

    def test_pqc_btc_larger_tx_than_classical(self):
        """ML-DSA-44 tx_size_bytes > ECDSA tx_size_bytes for Bitcoin."""
        classical_report = _bitcoin_report(algo="ECDSA")
        pqc_report = _bitcoin_report(algo="ML-DSA-44")
        # Compare any matching tx_type
        tx_type = "small_transfer"
        assert pqc_report.results[tx_type].tx_size_bytes > \
               classical_report.results[tx_type].tx_size_bytes

    def test_high_fee_destroys_dust_viability_btc(self):
        """At 500 sat/vbyte, dust_payment should not be viable."""
        report = _bitcoin_report(fee_rate=500.0)
        assert not report.results["dust_payment"].is_viable

    def test_whale_transfer_viable_at_high_fee_btc(self):
        """At moderate fees, whale_transfer should stay viable (high tolerance)."""
        report = _bitcoin_report(fee_rate=5.0)
        # Whale transfer has 0.1% tolerance on $50,000 → $50 max fee
        # At 5 sat/vbyte × ~300 bytes = 1500 sats ≈ $0.90 → viable
        assert report.results["whale_transfer"].is_viable

    def test_fee_multiplier_pqc_vs_classical(self):
        """PQC fee multiplier should be > 1 when PQC is larger than classical."""
        report = compute_tx_type_viability(
            chain="bitcoin",
            sig_algorithm="ML-DSA-44",
            base_fee_rate=1.0,
            native_asset_usd_price=60_000.0,
            classical_algo="ECDSA",
            classical_base_fee_rate=1.0,
        )
        for v in report.results.values():
            assert v.fee_multiplier_vs_classical > 1.0, (
                f"{v.tx_type}: multiplier={v.fee_multiplier_vs_classical}"
            )

    def test_fee_multiplier_classical_vs_classical_is_one(self):
        """When comparing ECDSA to ECDSA, multiplier == 1.0."""
        report = compute_tx_type_viability(
            chain="bitcoin",
            sig_algorithm="ECDSA",
            base_fee_rate=1.0,
            native_asset_usd_price=60_000.0,
            classical_algo="ECDSA",
            classical_base_fee_rate=1.0,
        )
        for v in report.results.values():
            assert abs(v.fee_multiplier_vs_classical - 1.0) < 1e-9

    def test_higher_fee_rate_reduces_viable_count(self):
        """More tx types become unviable as fee rate increases."""
        low  = _bitcoin_report(fee_rate=1.0)
        high = _bitcoin_report(fee_rate=1_000.0)
        assert len(high.viable_types) <= len(low.viable_types)

    def test_ethereum_classical_viable(self):
        """ECDSA at 20 gwei should have some viable types."""
        report = _ethereum_report(fee_rate=20.0, algo="ECDSA")
        assert len(report.viable_types) > 0

    def test_solana_classical_viable(self):
        """Ed25519 at very low fee should have all types viable."""
        report = _solana_report(fee_rate=0.0001, algo="Ed25519")
        assert len(report.viable_types) == len(report.results)


# ---------------------------------------------------------------------------
# Section 4: ChainViabilityReport properties
# ---------------------------------------------------------------------------

class TestChainViabilityReport:
    def test_viable_types_are_subset_of_results(self):
        report = _bitcoin_report(fee_rate=5.0)
        assert set(report.viable_types) <= set(report.results.keys())

    def test_unviable_types_are_subset_of_results(self):
        report = _bitcoin_report(fee_rate=5.0)
        assert set(report.unviable_types) <= set(report.results.keys())

    def test_viable_plus_unviable_equals_all(self):
        report = _bitcoin_report(fee_rate=5.0)
        combined = set(report.viable_types) | set(report.unviable_types)
        assert combined == set(report.results.keys())

    def test_viable_and_unviable_disjoint(self):
        report = _bitcoin_report(fee_rate=5.0)
        assert set(report.viable_types).isdisjoint(set(report.unviable_types))

    def test_viability_fraction_range(self):
        report = _bitcoin_report(fee_rate=5.0)
        frac = report.viability_fraction
        assert 0.0 <= frac <= 1.0

    def test_viability_fraction_all_viable(self):
        """At 0 fee rate, fraction should be 1.0 (all viable)."""
        report = _bitcoin_report(fee_rate=0.0)
        # fee=0 → estimated_fee=0 → 0 ≤ max_fee → all viable
        assert report.viability_fraction == 1.0

    def test_viability_fraction_none_viable(self):
        """At extreme fee, fraction should be 0.0."""
        report = _bitcoin_report(fee_rate=1_000_000.0)
        assert report.viability_fraction == 0.0

    def test_summary_table_returns_string(self):
        report = _bitcoin_report(fee_rate=5.0)
        table = report.summary_table()
        assert isinstance(table, str)
        assert len(table) > 0

    def test_summary_table_contains_chain_name(self):
        report = _bitcoin_report(fee_rate=5.0)
        assert "bitcoin" in report.summary_table().lower() or "Bitcoin" in report.summary_table()

    def test_summary_table_contains_all_tx_types(self):
        report = _bitcoin_report(fee_rate=5.0)
        table = report.summary_table()
        for tx_type in report.results:
            assert tx_type in table, f"Missing {tx_type} in summary_table"

    def test_empty_report_viability_fraction(self):
        report = ChainViabilityReport(
            chain="bitcoin", sig_algorithm="ECDSA",
            base_fee_rate=1.0, btc_usd_price=60_000.0,
        )
        assert report.viability_fraction == 0.0

    def test_btc_usd_price_stored(self):
        report = compute_tx_type_viability(
            chain="bitcoin", sig_algorithm="ECDSA",
            base_fee_rate=1.0, native_asset_usd_price=90_000.0,
        )
        assert report.btc_usd_price == 90_000.0


# ---------------------------------------------------------------------------
# Section 5: viability_sweep()
# ---------------------------------------------------------------------------

class TestViabilitySweep:
    def test_returns_dict(self):
        reports = viability_sweep("bitcoin", algorithms=["ECDSA", "Falcon-512"])
        assert isinstance(reports, dict)

    def test_all_algos_in_output(self):
        algos = ["ECDSA", "ML-DSA-44", "Falcon-512"]
        reports = viability_sweep("bitcoin", algorithms=algos)
        assert set(algos) == set(reports.keys())

    def test_each_value_is_chain_viability_report(self):
        reports = viability_sweep("ethereum", algorithms=["ECDSA", "ML-DSA-44"])
        for algo, report in reports.items():
            assert isinstance(report, ChainViabilityReport), algo

    def test_default_algorithms_non_empty(self):
        reports = viability_sweep("bitcoin")
        assert len(reports) >= 5  # at least classical + several PQC

    def test_pqc_multiplier_greater_than_classical_sweep(self):
        """In the sweep, PQC algos should have higher fees than ECDSA."""
        reports = viability_sweep("bitcoin", algorithms=["ECDSA", "ML-DSA-44"],
                                   base_fee_rate=1.0)
        ecdsa_fee = reports["ECDSA"].results["small_transfer"].estimated_fee_usd
        mldsa_fee = reports["ML-DSA-44"].results["small_transfer"].estimated_fee_usd
        assert mldsa_fee > ecdsa_fee

    def test_sweep_solana(self):
        reports = viability_sweep(
            "solana",
            algorithms=["Ed25519", "Falcon-512"],
            base_fee_rate=0.01,
            native_asset_usd_price=150.0,
        )
        assert "Ed25519" in reports
        assert "Falcon-512" in reports

    def test_sweep_all_results_have_same_tx_types(self):
        """All algos in a sweep must produce results for the same tx types."""
        algos = ["ECDSA", "ML-DSA-44", "SLH-DSA-128f"]
        reports = viability_sweep("bitcoin", algorithms=algos)
        tx_type_sets = [set(r.results.keys()) for r in reports.values()]
        assert all(s == tx_type_sets[0] for s in tx_type_sets)


# ---------------------------------------------------------------------------
# Section 6: Chain-specific fee model correctness
# ---------------------------------------------------------------------------

class TestChainFeeModels:
    def test_bitcoin_fee_proportional_to_rate(self):
        """Bitcoin fee scales linearly with sat/vbyte rate."""
        r1 = _bitcoin_report(fee_rate=1.0)
        r2 = _bitcoin_report(fee_rate=2.0)
        fee1 = r1.results["small_transfer"].estimated_fee_usd
        fee2 = r2.results["small_transfer"].estimated_fee_usd
        # fee2 should be approximately 2× fee1
        assert abs(fee2 / fee1 - 2.0) < 0.01, f"Expected 2×, got {fee2/fee1:.4f}"

    def test_ethereum_fee_positive(self):
        """Ethereum fee at 20 gwei should be positive."""
        report = _ethereum_report(fee_rate=20.0, algo="ECDSA")
        for v in report.results.values():
            assert v.estimated_fee_usd > 0.0

    def test_solana_fee_positive(self):
        """Solana fee should be positive even at near-zero priority rate."""
        report = _solana_report(fee_rate=0.0, algo="Ed25519")
        # Base 5000 lamports × 150 SOL/USD / 1e9 > 0
        for v in report.results.values():
            assert v.estimated_fee_usd > 0.0

    def test_bitcoin_pqc_tx_larger_than_classical(self):
        """ML-DSA-44 tx on Bitcoin must have a larger fee than ECDSA at same rate."""
        r_ecdsa = _bitcoin_report(fee_rate=10.0, algo="ECDSA")
        r_pqc   = _bitcoin_report(fee_rate=10.0, algo="ML-DSA-44")
        assert r_pqc.results["medium_transfer"].estimated_fee_usd > \
               r_ecdsa.results["medium_transfer"].estimated_fee_usd

    def test_slh_dsa_solana_fee_much_larger_than_ed25519(self):
        """SLH-DSA-128s (40,000 CUs) has far more CUs than Ed25519 (100 CUs).

        At a high priority fee rate the CU difference dominates the flat 5,000-lamport
        base fee, so the SLH-DSA fee should be substantially larger.
        """
        # Use SLH-DSA-128s (40,000 CUs) and a priority rate where CU cost dominates:
        # base=5000, priority=1.0 × 40000=40000 → total 45000 lamports (SLH)
        # base=5000, priority=1.0 × 100  =  100 → total  5100 lamports (Ed25519)
        # ratio ≈ 8.8× — well above 5×
        r_ed  = _solana_report(fee_rate=1.0, algo="Ed25519")
        r_slh = _solana_report(fee_rate=1.0, algo="SLH-DSA-128s")
        assert r_slh.results["defi_swap"].estimated_fee_usd > \
               r_ed.results["defi_swap"].estimated_fee_usd * 5


# ---------------------------------------------------------------------------
# Section 7: Edge cases and error handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_invalid_chain_raises_value_error(self):
        with pytest.raises(ValueError, match="No viability data"):
            compute_tx_type_viability(
                chain="dogecoin",
                sig_algorithm="ECDSA",
                base_fee_rate=1.0,
            )

    def test_unknown_algorithm_falls_back_gracefully(self):
        """Unknown algorithm should not raise — falls back to default sizes."""
        report = compute_tx_type_viability(
            chain="bitcoin",
            sig_algorithm="UnknownAlgo",
            base_fee_rate=1.0,
        )
        assert len(report.results) > 0

    def test_zero_fee_rate_all_viable(self):
        """Zero fee → all tx types viable (fee = 0 ≤ max_fee)."""
        report = _bitcoin_report(fee_rate=0.0)
        assert len(report.unviable_types) == 0

    def test_case_insensitive_chain(self):
        """Chain name normalisation: 'Bitcoin' and 'bitcoin' should work."""
        report = compute_tx_type_viability(
            chain="Bitcoin", sig_algorithm="ECDSA", base_fee_rate=1.0
        )
        assert report.chain == "bitcoin"

    def test_very_high_fee_all_unviable(self):
        """At astronomically high fees, no tx type should be viable."""
        report = _bitcoin_report(fee_rate=1_000_000.0)
        assert len(report.viable_types) == 0

    def test_native_asset_price_zero_edge(self):
        """Zero asset price → fee = 0 → all viable. Should not divide by zero."""
        report = compute_tx_type_viability(
            chain="bitcoin", sig_algorithm="ECDSA",
            base_fee_rate=10.0, native_asset_usd_price=0.0,
        )
        # fee = 0 USD → viable (or no crash)
        assert isinstance(report, ChainViabilityReport)

    def test_multiplier_when_classical_rate_differs(self):
        """fee_multiplier_vs_classical reflects ratio of fees."""
        report = compute_tx_type_viability(
            chain="bitcoin",
            sig_algorithm="ECDSA",
            base_fee_rate=10.0,
            native_asset_usd_price=60_000.0,
            classical_algo="ECDSA",
            classical_base_fee_rate=5.0,  # half the rate
        )
        for v in report.results.values():
            # PQC rate 10, classical rate 5, same algo → multiplier ≈ 2.0
            assert abs(v.fee_multiplier_vs_classical - 2.0) < 0.01, (
                f"{v.tx_type}: multiplier={v.fee_multiplier_vs_classical}"
            )
