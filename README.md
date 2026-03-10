# PQC Cross-Chain Simulator

A research-grade simulation and analysis framework quantifying how post-quantum cryptography (PQC) affects throughput, propagation, fees, and consensus across **Solana**, **Bitcoin**, and **Ethereum**.

> **Branch `research-v2`** — 425 tests passing, 2,800+ lines of new analysis code.

---

## What This Project Does

Blockchains rely on digital signatures (Ed25519, ECDSA, BLS) that are vulnerable to quantum computers via Shor's algorithm. NIST-standardised PQC replacements (FIPS 204/205) are **10–460× larger** and verification is **3–100× slower**. This project quantifies the impact using three complementary approaches:

### 1. Solana DES Simulation (High-Throughput Model)

A 75-node discrete-event simulation with realistic network conditions, sweeping PQC adoption from 0–100%. This is the right methodology for Solana because the bottleneck is **NIC contention and slot timing** at 400ms block intervals.

- NIC contention: upload bandwidth shared across concurrent gossip peers
- Turbine routing: Solana's layered tree propagation (fanout=200)
- Vote transaction overhead: validators submit ~1 vote tx per slot
- Dynamic fee market: priority-fee model with economic failure tracking
- Validator economics: break-even stale rate, exit probability, network shrinkage
- Mainnet calibration: validated against observed Solana metrics (skip rate, P90 propagation, TPS)
- Statistical hardening: multi-seed sweeps with confidence intervals and bootstrap thresholds

### 2. Bitcoin & Ethereum Analytical Models (Capacity-Constrained Chains)

For Bitcoin and Ethereum, the bottleneck is **block capacity** (weight units, gas), not NIC contention. Integration-percentage sweeps don't capture the right dynamics. Instead, these analytical models compute exact capacity/fee/consensus impacts per PQC algorithm:

**Bitcoin:**
- Block weight analysis across 7 PQC algorithms under 3 witness discount policies
- Fee market simulation: greedy block construction from mixed mempools
- Result: FALCON-512 reduces capacity 77%; Dilithium5 by 94%; SPHINCS+-256s by 99%

**Ethereum:**
- Gas cost analysis: per-algorithm TPS for simple, ERC-20, and complex transactions
- EIP-1559 base fee dynamics with demand elasticity
- Consensus layer: attestation sizes without BLS aggregation, P2P bandwidth requirements
- Validator economics: bandwidth/storage overhead, centralisation risk
- Result: Only FALCON-512/1024 are consensus-feasible at 100 Mbps; Dilithium2+ exceeds validator bandwidth

### 3. Migration Transition Model

Sweeps PQC adoption from 0→100% on both chains to identify critical thresholds during the transition period where legacy and PQC signatures coexist.

| Chain | Algorithm | 50% TPS Drop | Gas Limit Increase | Consensus Feasible |
|-------|-----------|-------------|--------------------|--------------------|
| Bitcoin | FALCON-512 | 35% adoption | — | — |
| Bitcoin | Dilithium3 | 10% adoption | — | — |
| Bitcoin | SPHINCS+-256s | 5% adoption | — | — |
| Ethereum | FALCON-512 | — | 50% adoption | Yes |
| Ethereum | Dilithium2 | — | 25% adoption | No |
| Ethereum | SPHINCS+-256s | — | 5% adoption | No |

---

## Quick Start

### Running the Chain Analysis (No Dependencies)

The Bitcoin/Ethereum analytical models require no external dependencies beyond Python 3.10+:

```bash
# Full analysis — all chains, all algorithms (~10 seconds)
python run_chain_analysis.py --chain all

# Bitcoin only
python run_chain_analysis.py --chain btc

# Ethereum only
python run_chain_analysis.py --chain eth

# Filter by algorithm family
python run_chain_analysis.py --algorithms falcon
python run_chain_analysis.py --algorithms dilithium
python run_chain_analysis.py --algorithms sphincs
```

Output goes to `results/bitcoin/`, `results/ethereum/`, `results/migration/`, and `results/summary_tables.md`.

### Running the Solana Sweep

```bash
# Quick mode (5 seeds, ~3 min)
MOCK_PQC=1 python run_enhanced_sweep.py --chain solana --quick

# Full publication sweep (30 seeds, ~hours)
MOCK_PQC=1 python run_enhanced_sweep.py --chain solana
```

### Running the Original Monte Carlo Sweep

```bash
MOCK_PQC=1 python run_experiments.py
```

### Running the Streamlit UI

```bash
# Docker (recommended)
docker compose up --build         # http://localhost:8501

# Local
pip install -r requirements.txt
PQC_MOCK=1 streamlit run app/pqc_demo_streamlit.py
```

---

## Running Tests

```bash
# All 425 tests (mock mode, no liboqs required)
MOCK_PQC=1 pytest tests/ -v \
  --ignore=tests/test_kem.py \
  --ignore=tests/test_signatures.py \
  --ignore=tests/test_aggregation.py \
  --ignore=tests/test_ui_integration.py \
  --ignore=tests/test_charts.py

# Chain analysis tests only (75 tests)
MOCK_PQC=1 pytest tests/test_chain_analysis/ -v

# Phase B tests (NIC contention, routing)
MOCK_PQC=1 pytest tests/test_phase_b/ -v

# Phase G tests (fee market, validator economics, calibration)
MOCK_PQC=1 pytest tests/test_phase_g/ -v

# With liboqs (includes KEM, signature, aggregation tests)
pytest tests/ -v
```

---

## Key Results

### Bitcoin: Block Capacity Under PQC

| Algorithm | Sig (B) | PK (B) | Txs/Block | TPS | Reduction |
|-----------|---------|--------|-----------|-----|-----------|
| ECDSA (baseline) | 72 | 33 | 4,683 | 7.80 | — |
| FALCON-512 | 666 | 897 | 1,061 | 1.77 | 77% |
| Dilithium2 | 2,420 | 1,312 | 493 | 0.82 | 89% |
| Dilithium5 | 4,595 | 2,592 | 266 | 0.44 | 94% |
| SPHINCS+-256s | 29,792 | 64 | 66 | 0.11 | 99% |

### Ethereum: Gas Cost Impact

| Algorithm | Simple TPS | ERC-20 TPS | Reduction | Consensus Feasible |
|-----------|-----------|------------|-----------|-------------------|
| ECDSA (baseline) | 97.5 | 35.8 | — | Yes (BLS) |
| FALCON-512 | 45.3 | 25.2 | 54% | Yes |
| Dilithium2 | 26.7 | 18.2 | 73% | No |
| SPHINCS+-256s | 3.2 | 3.0 | 97% | No |

### Solana: DES Simulation (50% PQC, Enhanced Sweep)

| Metric | Value |
|--------|-------|
| Stale rate | 54% |
| P90 propagation | 654 ms |
| Economic failure rate | 28.6% |
| Vote overhead | 0.45% |
| Break-even stale rate | 83.5% |

---

## Project Structure

```
simulator/                     Discrete-event simulation engine
  core/
    engine.py                  DES engine with NIC contention + chain-specific capacity
    phase2_engine.py           Phase 2/3: Poisson arrivals, mempool, fee market, vote overhead
    events.py                  Event types and priority ordering
  network/
    node.py                    Node model with CPU scheduling + NIC bandwidth sharing
    topology.py                Network topology with geographic latency matrix
    propagation.py             Block/Transaction dataclasses, percentile computation
    routing.py                 Chain-specific routing (Turbine, CompactBlock, EthHybrid)
  mempool/
    mempool.py                 Bounded mempool with fee-rate eviction
    algorithm_mix.py           PQC/classical algorithm sampling + Poisson arrival model
  chains/
    base.py                    Chain configurations (Solana, Bitcoin, Ethereum)
    bitcoin_specific.py        UTXO tx model with SegWit witness discount
    ethereum_specific.py       Account model with gas metering
  economics/
    fee_market.py              Dynamic fee markets (EIP-1559, first-price, priority fee)
    validator_economics.py     Break-even analysis, exit probability, network shrinkage
  calibration/
    mainnet_data.py            Hardcoded mainnet observations (Solana/ETH/BTC)
    validation.py              Validation table + gap analysis generation
  models/
    bandwidth.py               Validator/full-node hardware tier sampling
    latency.py                 Latency model (distance-dependent)
  results.py                   Result dataclasses
  state.py                     Simulation state (event queue, block registry)

analysis/                      Analytical models (not simulation-based)
  pqc_algorithms.py            Algorithm catalogue: sizes, gas estimates, security levels
  bitcoin_pqc_analysis.py      Block weight, witness policies, fee market simulation
  ethereum_pqc_analysis.py     Gas costs, EIP-1559 dynamics, consensus layer, validator econ
  migration_model.py           Transition curves + threshold detection (BTC + ETH)
  statistical_analysis.py      CIs, bootstrap thresholds, censoring-aware metrics

blockchain/                    Static block-space impact models
  chain_models.py              Solana, Bitcoin, Ethereum throughput retention
  verification.py              Signature verification time profiles
  aggregation.py               Aggregation scheme models (BLS, Falcon tree, ML-DSA batch)

pqc_lib/                       PQC algorithm wrappers
  signatures.py                ML-DSA, SLH-DSA, Falcon, Ed25519, ECDSA, Schnorr + hybrids
  kem.py                       ML-KEM (FIPS 203)
  mock.py                      Deterministic mocks with NIST-accurate artifact sizes
  utils.py                     Timing and memory profiling utilities

app/                           Streamlit UI
  pqc_demo_streamlit.py        Main orchestrator
  tabs/                        Overview, Algorithms, Block Space, PQC Shock Simulator
  components/charts.py         Reusable Plotly chart builders

run_chain_analysis.py          BTC/ETH analytical runner (deterministic, <10s)
run_enhanced_sweep.py          Solana publication sweep (30 seeds, fee market, votes, econ)
run_multi_chain_sweep.py       Multi-chain DES sweep infrastructure
run_experiments.py             Original Monte Carlo sweep (generates pqc_sweep.csv)
run_sensitivity_sweeps.py      Sensitivity analysis with alternative algorithm mixes

results/                       All output data
  bitcoin/                     Block capacity, witness policy, fee market CSVs
  ethereum/                    Gas cost, EIP-1559, consensus layer, validator economics CSVs
  migration/                   Transition curves + threshold summary CSVs
  calibration/                 Solana validation table + gap analysis
  summary_tables.md            Publication-ready markdown tables
  solana_sweep_enhanced.csv    Enhanced Solana sweep (5 seeds × 21 PQC levels)
  pqc_sweep.csv                Original 210-run sweep
  sensitivity_falcon.csv       Falcon-dominant sensitivity (210 runs)
  sensitivity_mldsa_only.csv   ML-DSA-only sensitivity (210 runs)

tests/                         425 tests (pytest)
  test_chain_analysis/         75 tests: BTC analysis, ETH analysis, migration model
  test_phase_b/                NIC contention, routing strategies, multi-chain
  test_phase_g/                Fee market, validator economics, calibration, votes, stats
  test_phase2/                 Mempool, Phase 2 engine, Poisson
  test_simulator/              Engine, latency, topology
  test_solana_model.py         Solana-specific model tests
  test_verification.py         Verification timing tests
```

## Signature Algorithms

| Algorithm | Type | Standard | Sig Size | PK Size | NIST Level |
|-----------|------|----------|----------|---------|------------|
| Ed25519 | Classical | RFC 8032 | 64 B | 32 B | N/A |
| ECDSA | Classical | FIPS 186 | 72 B | 33 B | N/A |
| BLS12-381 | Classical | — | 96 B | 48 B | N/A |
| FALCON-512 | PQC | Pending (FN-DSA) | 666 B | 897 B | 1 |
| FALCON-1024 | PQC | Pending (FN-DSA) | 1,280 B | 1,793 B | 5 |
| ML-DSA-44 (Dilithium2) | PQC | FIPS 204 | 2,420 B | 1,312 B | 2 |
| ML-DSA-65 (Dilithium3) | PQC | FIPS 204 | 3,293 B | 1,952 B | 3 |
| ML-DSA-87 (Dilithium5) | PQC | FIPS 204 | 4,595 B | 2,592 B | 5 |
| SLH-DSA-128s (SPHINCS+-128s) | PQC | FIPS 205 | 7,856 B | 32 B | 1 |
| SLH-DSA-256s (SPHINCS+-256s) | PQC | FIPS 205 | 29,792 B | 64 B | 5 |

## Blockchain Models

| Chain | Approach | Baseline Sig | Block Limit | Block Time | Key Feature |
|-------|----------|-------------|-------------|------------|-------------|
| Solana | DES simulation | Ed25519 | ~6 MB | 400 ms | NIC contention, Turbine routing, vote overhead |
| Bitcoin | Analytical model | ECDSA/Schnorr | 4 MWU | 10 min | SegWit witness discount, fee market dynamics |
| Ethereum | Analytical model | ECDSA + BLS | 30M gas | 12 s | Gas costing, EIP-1559, consensus layer impact |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_PQC` / `PQC_MOCK` | `0` | Set to `1` for mock mode (no liboqs needed) |

## Author

**Shahbaz Zulkernain**
MPhys Physics, University of St Andrews (Class of 2028)
St Andrews Blockchain Society — PQC Research Lead
