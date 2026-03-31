"""Top-level pytest configuration for UOSA_PQC test suite.

TEST DIRECTORY MAP
──────────────────

tests/
├── conftest.py                    ← This file. Registers all custom markers.
│
├── (flat files) ─────────────────── research-v2 unit tests (new modules)
│   ├── test_bitcoin_vulnerability.py   simulator/chains/bitcoin_vulnerability.py
│   ├── test_ethereum_gas_schedule.py   simulator/chains/ethereum_specific.py (PQC gas)
│   ├── test_solana_vote_overhead.py    simulator/chains/solana_specific.py
│   ├── test_dual_sig_migration.py      simulator/migration/dual_sig.py
│   ├── test_user_agents.py             simulator/economics/user_agents.py
│   ├── test_block_builder.py           simulator/economics/block_builder.py
│   ├── test_calibration.py             simulator/calibration/baseline.py (NEW runner)
│   └── test_engine_integration.py      DESEngine + dual-sig + calibration integration
│
├── test_simulator/       ─────────── Phase 1 DESEngine unit tests
│   ├── test_engine.py                  DESEngine core event loop
│   ├── test_latency_model.py           simulator/models/latency.py
│   └── test_topology.py               simulator/network/topology.py
│
├── test_phase2/          ─────────── Phase2Engine integration tests
│   ├── test_algorithm_mix.py           AlgorithmMixGenerator, AlgorithmMixConfig
│   ├── test_mempool.py                 GlobalMempool, eviction, fee-rate ordering
│   ├── test_phase2_engine.py           Phase2Engine full runs (all 3 chains)
│   └── test_poisson.py                PoissonArrivalModel inter-arrival stats
│
├── test_phase_b/         ─────────── Phase B realism integration tests
│   ├── test_multi_chain.py             DESEngine + Phase2Engine on Bitcoin/ETH/Solana
│   ├── test_nic_contention.py          Upload bandwidth sharing across gossip peers
│   └── test_routing.py                Chain-specific routing (Turbine, compact blocks)
│
├── test_phase_g/         ─────────── Phase G economics integration tests
│   ├── test_calibration.py             simulator.calibration.runner + mainnet_data
│   │                                   NOTE: different from tests/test_calibration.py
│   │                                   (which tests simulator.calibration.baseline)
│   ├── test_chain_specific.py          Bitcoin weight units, Ethereum gas metering
│   ├── test_fee_market.py              DynamicFeeMarket EIP-1559 / first-price
│   ├── test_statistical.py             ConfidenceInterval, sensitivity metrics
│   ├── test_validator_economics.py     ValidatorEconomics exit/profitability model
│   └── test_vote_overhead.py           Solana vote tx injection via Phase2Engine
│
├── test_chain_analysis/  ─────────── Static analytical model tests
│   ├── test_bitcoin_analysis.py        analysis/bitcoin_pqc_analysis.py
│   ├── test_ethereum_analysis.py       analysis/ethereum_pqc_analysis.py
│   └── test_migration_model.py         analysis/migration_model.py
│
└── (other flat files)
    ├── test_aggregation.py             blockchain/aggregation.py (BLS)
    ├── test_charts.py                  app/components/charts.py
    ├── test_kem.py                     pqc_lib/kem.py
    ├── test_signatures.py              pqc_lib/signatures.py
    ├── test_solana_model.py            blockchain/chain_models.py Solana path
    ├── test_ui_integration.py          Streamlit UI (skipped in CI — requires display)
    └── test_verification.py            blockchain/verification.py

RUNNING THE SUITE
─────────────────
# Full suite (exclude UI tests which require a display):
  MOCK_PQC=1 pytest tests/ --ignore=tests/test_ui_integration.py

# New research-v2 modules only (fast, ~10s):
  MOCK_PQC=1 pytest tests/test_bitcoin_vulnerability.py tests/test_ethereum_gas_schedule.py \\
    tests/test_solana_vote_overhead.py tests/test_dual_sig_migration.py \\
    tests/test_user_agents.py tests/test_block_builder.py \\
    tests/test_calibration.py tests/test_engine_integration.py

# Phase G + Phase B integration (slower, full engine runs):
  MOCK_PQC=1 pytest tests/test_phase2/ tests/test_phase_b/ tests/test_phase_g/
"""
import pytest


def pytest_configure(config):
    """Register custom markers to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "phase2: Phase 2/3 stochastic engine integration tests"
    )
    config.addinivalue_line(
        "markers",
        "phase_b: Phase B NIC contention and multi-chain routing integration tests"
    )
    config.addinivalue_line(
        "markers",
        "phase_g: Phase G fee market, calibration, and economics integration tests"
    )
    config.addinivalue_line(
        "markers",
        "slow: Tests that take more than 5 seconds to run"
    )
    config.addinivalue_line(
        "markers",
        "integration: Full engine runs (not pure unit tests)"
    )
