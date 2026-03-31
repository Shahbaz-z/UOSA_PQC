"""Pytest configuration for Phase 2/3 engine integration tests.

SCOPE: Tests in this directory validate Phase2Engine — the stochastic
PQC shock simulator that wraps DESEngine with:
  - Poisson transaction arrivals
  - GlobalMempool with fee-rate eviction
  - Heterogeneous algorithm blocks
  - Per-transaction CPU-locked verification

RELATIONSHIP TO OTHER TEST DIRS:
  tests/test_simulator/    — DESEngine (Phase 1) unit tests
  tests/test_phase2/       — Phase2Engine integration tests  ← YOU ARE HERE
  tests/test_phase_b/      — NIC contention + multi-chain routing integration tests
  tests/test_phase_g/      — Fee market, calibration, vote overhead, validator economics
  tests/test_chain_analysis/ — Static analytical models (Bitcoin/Ethereum/migration)
  tests/                   — Flat unit tests for new research-v2 modules
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "phase2: Phase 2/3 stochastic engine integration tests (slower, use MOCK_PQC=1)"
    )
