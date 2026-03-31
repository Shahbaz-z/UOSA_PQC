"""Pytest configuration for Phase G integration tests.

SCOPE: Tests in this directory validate the Phase G simulator upgrades:
  - DynamicFeeMarket (EIP-1559, first-price auction, Solana priority fees)
  - Calibration runner and mainnet_data/validation modules
  - Vote transaction overhead (Solana-specific block-space injection)
  - ValidatorEconomics (exit dynamics, profitability model)
  - StatisticalAnalysis (confidence intervals, sensitivity metrics)
  - Chain-specific models (Bitcoin weight units, Ethereum gas, Solana CU)

NOTE on calibration overlap:
  tests/test_phase_g/test_calibration.py  — tests simulator.calibration.runner,
      simulator.calibration.mainnet_data, and simulator.calibration.validation
  tests/test_calibration.py               — tests the NEW simulator.calibration.baseline
      module (CalibrationRunner, CALIBRATION_TARGETS, CalibrationError)
  These are DIFFERENT modules; both test files are needed.

RELATIONSHIP TO OTHER TEST DIRS:
  tests/test_simulator/    — DESEngine (Phase 1) unit tests
  tests/test_phase2/       — Phase2Engine integration tests
  tests/test_phase_b/      — NIC contention + multi-chain routing
  tests/test_phase_g/      — Fee market, calibration, vote overhead  ← YOU ARE HERE
  tests/test_chain_analysis/ — Static analytical models
  tests/                   — Flat unit tests for new research-v2 modules
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "phase_g: Phase G fee market, calibration, and economics integration tests"
    )
