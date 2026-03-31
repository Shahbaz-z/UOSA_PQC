"""Pytest configuration for Phase B integration tests.

SCOPE: Tests in this directory validate the Phase B simulator upgrades:
  - NIC contention model (upload bandwidth sharing across gossip peers)
  - Multi-chain propagation (Bitcoin compact blocks, Ethereum hybrid, Solana Turbine)
  - Routing strategy correctness (fanout, deduplication, chain-specific paths)

These are integration tests: they run both DESEngine and Phase2Engine
on all three chains and verify that Phase B realism flags behave correctly.

RELATIONSHIP TO OTHER TEST DIRS:
  tests/test_simulator/    — DESEngine (Phase 1) unit tests
  tests/test_phase2/       — Phase2Engine integration tests
  tests/test_phase_b/      — NIC contention + multi-chain routing  ← YOU ARE HERE
  tests/test_phase_g/      — Fee market, calibration, vote overhead, validator economics
  tests/test_chain_analysis/ — Static analytical models
  tests/                   — Flat unit tests for new research-v2 modules
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "phase_b: Phase B NIC contention and multi-chain routing integration tests"
    )
