"""Tests for mainnet calibration and validation."""

import os
import sys
import pytest

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from simulator.calibration.mainnet_data import get_mainnet_data, MAINNET_DATA
from simulator.calibration.validation import (
    generate_validation_table,
    generate_gap_analysis,
    ValidationRow,
)


class TestMainnetData:
    """Test mainnet data retrieval."""

    def test_all_chains_available(self):
        for chain in ["solana", "ethereum", "bitcoin"]:
            data = get_mainnet_data(chain)
            assert data.chain == chain

    def test_case_insensitive(self):
        data = get_mainnet_data("Solana")
        assert data.chain == "solana"

    def test_unknown_chain_raises(self):
        with pytest.raises(ValueError, match="No mainnet data"):
            get_mainnet_data("cardano")

    def test_solana_reasonable_values(self):
        data = get_mainnet_data("solana")
        assert 0.01 < data.skip_rate < 0.20
        assert 100 < data.p90_propagation_ms < 2000
        assert data.avg_block_time_ms == 400.0
        assert data.validator_count > 1000

    def test_ethereum_reasonable_values(self):
        data = get_mainnet_data("ethereum")
        assert data.avg_block_time_ms == 12_000.0
        assert data.validator_count > 100_000

    def test_bitcoin_reasonable_values(self):
        data = get_mainnet_data("bitcoin")
        assert data.avg_block_time_ms == 600_000.0
        assert data.skip_rate < 0.01

    def test_notes_non_empty(self):
        for chain in ["solana", "ethereum", "bitcoin"]:
            data = get_mainnet_data(chain)
            assert len(data.notes) > 0


class TestValidationTable:
    """Test validation table generation."""

    def test_basic_table(self):
        sim = {
            "stale_rate": 0.0,
            "avg_propagation_p90_ms": 150.0,
            "effective_tps": 5000.0,
            "block_time_ms": 400.0,
        }
        rows = generate_validation_table(
            "solana", sim, output_dir="/tmp/test_calibration"
        )
        assert len(rows) == 4
        assert all(isinstance(r, ValidationRow) for r in rows)

    def test_csv_saved(self):
        sim = {
            "stale_rate": 0.0,
            "avg_propagation_p90_ms": 150.0,
            "effective_tps": 5000.0,
            "block_time_ms": 400.0,
        }
        rows = generate_validation_table(
            "solana", sim, output_dir="/tmp/test_calibration"
        )
        assert os.path.exists("/tmp/test_calibration/solana_validation_table.csv")

    def test_direction_classification(self):
        """Stale rate = 0 vs mainnet 5% should be optimistic."""
        sim = {"stale_rate": 0.0, "avg_propagation_p90_ms": 0.0,
               "effective_tps": 0.0, "block_time_ms": 400.0}
        rows = generate_validation_table(
            "solana", sim, output_dir="/tmp/test_calibration"
        )
        stale_row = [r for r in rows if r.metric == "Skip/Stale Rate"][0]
        assert stale_row.direction == "Optimistic"

    def test_row_to_dict(self):
        row = ValidationRow(
            metric="Test", simulated=1.0, observed=2.0,
            gap=-1.0, gap_pct=-50.0, direction="Optimistic",
            omission="Test omission",
        )
        d = row.to_dict()
        assert d["Metric"] == "Test"
        assert d["Direction"] == "Optimistic"


class TestGapAnalysis:
    """Test markdown gap analysis generation."""

    def test_basic_gap_analysis(self):
        sim = {
            "stale_rate": 0.0,
            "avg_propagation_p90_ms": 150.0,
            "effective_tps": 5000.0,
            "block_time_ms": 400.0,
        }
        rows = generate_validation_table(
            "solana", sim, output_dir="/tmp/test_calibration"
        )
        md = generate_gap_analysis(
            "solana", rows, output_dir="/tmp/test_calibration"
        )
        assert "# Calibration Gap Analysis" in md
        assert "Optimistic" in md or "Pessimistic" in md or "Matched" in md

    def test_md_file_saved(self):
        sim = {"stale_rate": 0.0, "avg_propagation_p90_ms": 0.0,
               "effective_tps": 0.0, "block_time_ms": 400.0}
        rows = generate_validation_table(
            "solana", sim, output_dir="/tmp/test_calibration"
        )
        generate_gap_analysis("solana", rows, output_dir="/tmp/test_calibration")
        assert os.path.exists("/tmp/test_calibration/solana_gap_analysis.md")
