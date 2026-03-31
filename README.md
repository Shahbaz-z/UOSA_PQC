# PQC Cross-Chain Simulator

A research-grade simulation and analysis framework quantifying how post-quantum cryptography (PQC) affects throughput, propagation, fees, and consensus across **Solana**, **Bitcoin**, and **Ethereum**.

> **Branch `research-v2`** — 942 tests passing · commit `d6bf239`

---

## What This Project Does

Blockchains rely on digital signatures (Ed25519, ECDSA, BLS) vulnerable to quantum computers via Shor's algorithm. NIST-standardised PQC replacements (FIPS 204/205) are **10–460× larger** and verification is **3–100× slower**. This project quantifies the impact using three complementary approaches:

### 1. Solana DES Simulation

A 75-node discrete-event simulation sweeping PQC adoption from 0–100%. Solana's 400 ms slot window makes it the only major chain where propagation latency is a binding constraint — the DES engine models this directly.

**Engine (`DESEngine` / `Phase2Engine`):**
- NIC contention: upload bandwidth serialised across concurrent gossip peers
- Turbine routing: bounded-fanout tree propagation (fanout = 200)
- Vote transaction injection: per-slot Ed25519 vote txs at configurable fraction
- Poisson transaction arrivals filling a bounded 100 MB mempool
- Dynamic fee market: EIP-1559-style priority fee with PQC size pressure
- Heterogeneous PQC blocks: mixed classical + PQC algorithm fractions
- Per-transaction CPU verification with min-heap core scheduling

**Phase 4 — Agent-Based Economics Layer (`simulator/economics/`):**
- `user_agents.py` — five archetypes (retail, whale, arb\_bot, defi\_protocol, exchange) with chain-specific population mixes; fee-elastic demand, batching, and L2 migration
- `block_builder.py` — priority block construction; `verification_cost_weight` blends fee/resource score with verify-efficiency, exposing rational validator censorship incentive
- `tx_viability.py` — analytical viability assessment: identifies which transaction types become economically irrational (fee > value) under PQC fee pressure across all three chains
- Demand metrics output: `demand_txs_submitted`, `demand_txs_abandoned`, `demand_l2_migrations`, `avg_demand_reduction_pct`, `blocks_elevated`

**Calibration:** mainnet-validated against Solana skip rate, P90 propagation, TPS baselines with per-metric tolerances.

### 2. Bitcoin & Ethereum Analytical Models

For Bitcoin and Ethereum the bottleneck is **block capacity** (weight units, gas), not NIC contention. Analytical models compute exact capacity, fee, and consensus impacts per PQC algorithm:

**Bitcoin (`simulator/chains/bitcoin_specific.py`, `bitcoin_vulnerability.py`):**
- Block weight: `tx_weight = base_size × 4 + witness_size × 1` — BIP 141 correct (marker+flag at 1 WU each, not 4)
- Witness discount means PQC signatures pay only 25% of their byte weight
- Compact block relay (`CompactBlockRouting`): efficiency now scales with PQC adoption — collapses from 10% to 100% of full block size as relay nodes lose mempool overlap
- Quantum exposure model: P2PK (immediate) + P2PKH/P2WPKH/P2WSH/P2TR (deferred on spend); P2TR at full 1.0× weight — tweaked Schnorr keys are equally susceptible to Shor's algorithm; spend velocity modelled separately via `SPEND_FREQUENCY_FACTOR`
- CRQC probability: logistic CDF centred on 2035 ± 4 years; Mosca urgency score

**Ethereum (`simulator/chains/ethereum_specific.py`):**
- Gas cost: `base(21k) + calldata(40 gas/byte, EIP-7623 Pectra) + PQC precompile + AA overhead`
- `dual_sig_gas()`: hybrid EIP-4337/EIP-7702 migration cost (classical + PQC + AA overhead)
- Announcement propagation: 48-byte `NewBlockHashes` (devp2p eth/68 accurate)

### 3. Migration Transition Model

Sweeps PQC adoption from 0 → 100% on all three chains to identify critical thresholds during coexistence of classical and PQC signatures.

---

## Architecture

```
simulator/core/engine.py          DESEngine — heapq event loop, NIC contention, Turbine/routing
simulator/core/phase2_engine.py   Phase2Engine — wraps DESEngine; mempool, fee market,
                                  heterogeneous blocks, agent demand model
```

The two engines have a strict parent/child relationship: `Phase2Engine` constructs a `DESEngine` internally and monkey-patches `_create_block` and `_handle_block_received` at runtime.

**Routing strategies (`simulator/network/routing.py`):**

| Chain | Strategy | Key property |
|-------|----------|-------------|
| Solana | `TurbineRouting(fanout=200)` | Bounded-fanout per node; layer delay via `isinstance` check |
| Bitcoin | `CompactBlockRouting` | `compact_fraction = 0.10 + 0.90 × pqc_fraction` — degrades at high PQC |
| Ethereum | `EthHybridRouting` | Direct to √N peers + 48-byte announcement to remainder |

**Validator hardware (`simulator/models/bandwidth.py`):**  
`SOLANA_VALIDATOR_TIERS` floors home-tier upload at 300 Mbps (Solana's documented minimum). `sample_validator_config(chain="solana")` selects the Solana-specific tier table automatically.

---

## Quick Start

### Solana Sweep

```bash
# Quick sweep (5 seeds, ~3 min)
MOCK_PQC=1 python run_enhanced_sweep.py --chain solana --quick

# Full publication sweep (30 seeds)
MOCK_PQC=1 python run_enhanced_sweep.py --chain solana

# Original Monte Carlo sweep (generates pqc_sweep.csv)
MOCK_PQC=1 python run_experiments.py
```

### Bitcoin / Ethereum Analysis

```bash
# All chains, all algorithms (~10 s, no liboqs required)
python run_chain_analysis.py --chain all

python run_chain_analysis.py --chain btc
python run_chain_analysis.py --chain eth
python run_chain_analysis.py --algorithms falcon
```

### Streamlit UI

```bash
# Docker (recommended)
docker compose up --build          # http://localhost:8501

# Local
pip install -r requirements.txt
PQC_MOCK=1 streamlit run app/pqc_demo_streamlit.py
```

---

## Running Tests

```bash
# All 942 tests (mock mode — no liboqs required)
MOCK_PQC=1 python -m pytest tests/ --ignore=tests/test_ui_integration.py -q
```

Key test files added in `research-v2`:

| File | Tests | Coverage |
|------|-------|----------|
| `test_bitcoin_vulnerability.py` | UTXO exposure model, CRQC timeline, P2TR weight |
| `test_ethereum_gas_schedule.py` | Gas schedule, EIP-7623 calldata, dual-sig AA |
| `test_solana_vote_overhead.py` | Vote tx injection, CU saturation |
| `test_dual_sig_migration.py` | Migration curve, logistic k=8, phases cache |
| `test_user_agents.py` | Agent archetypes, fee elasticity, L2 migration |
| `test_block_builder.py` | Priority scoring, verification_cost_weight blending |
| `test_tx_viability.py` | compute_tx_type_viability(), viability_sweep(), breakeven |
| `test_engine_agent_integration.py` | Phase2Engine demand metrics, BUG-C guard |
| `test_engine_integration.py` | Full DES runs, stale rate, SimulationResult structure |
| `test_propagation_bugs.py` | Nearest-rank percentile, NIC contention, EthHybrid |
| `test_engine_consistency.py` | NIC representative_task, lognormal block util |
| `test_architecture_fixes.py` | P2TR weight=1.0, spend-adjusted fractions, dual-sig |
| `test_audit_fixes.py` | PQC fee double-penalty, elapsed_ms boundary, stale rate |
| `test_final_assessment.py` | is_eth_announcement alias, verification_failure_rate |
| `test_calibration.py` | NaN guard, per-metric tolerances |

---

## Key Results

### Solana: DES Simulation (0% PQC baseline, fee market enabled)

| Metric | Value |
|--------|-------|
| P90 propagation | ~291 ms (72.8% of 400 ms slot) |
| Stale rate (0% PQC) | ~23% |
| Stale rate (100% ML-DSA-65) | ~54% |
| Economic failure rate (50% PQC) | ~28.6% |
| Vote overhead (226 B × 50 validators) | ~0.9% of block |
| Demand reduction at 5× fee pressure | 40–60% (agent model) |

### Bitcoin: Block Capacity Under PQC (SegWit witness discount applied)

| Algorithm | Sig (B) | PK (B) | vsize (vbytes) | Txs/Block | TPS | Capacity loss |
|-----------|---------|--------|----------------|-----------|-----|---------------|
| ECDSA (baseline) | 72 | 33 | ~141 | ~4,600 | 7.7 | — |
| Falcon-512 | 666 | 897 | ~490 | ~1,060 | 1.8 | −77% |
| ML-DSA-44 | 2,420 | 1,312 | ~1,165 | ~438 | 0.7 | −90% |
| ML-DSA-65 | 3,309 | 1,952 | ~1,585 | ~322 | 0.5 | −93% |
| SLH-DSA-128s | 7,856 | 32 | ~2,018 | ~253 | 0.4 | −94% |
| SLH-DSA-128f | 17,088 | 32 | ~4,298 | ~119 | 0.2 | −97% |

Compact block relay degrades from 10% → 100% of full block size as PQC adoption grows (relay nodes have zero PQC mempool overlap).

### Ethereum: Gas Cost Impact (40 gas/byte calldata, EIP-7623 Pectra)

| Algorithm | Tx Gas | Simple TPS (60M gas) | vs ECDSA | Dual-sig + AA gas |
|-----------|--------|----------------------|----------|-------------------|
| ECDSA | ~24,500 | ~2,450 | — | — |
| Falcon-512 | ~93,000 | ~645 | −74% | ~207,000 |
| ML-DSA-44 | ~183,000 | ~328 | −87% | ~390,000 |
| ML-DSA-65 | ~232,000 | ~259 | −89% | ~475,000 |
| SLH-DSA-128s | ~353,000 | ~170 | −93% | ~630,000 |
| SLH-DSA-128f | ~697,000 | ~86 | −96% | ~1,120,000 |

### Bitcoin Quantum Exposure

| Address Type | Mechanism | Exposure | Weight |
|-------------|-----------|----------|--------|
| P2PK | Raw public key on-chain | Immediate | 1.0× |
| P2PKH / P2WPKH / P2WSH | Pubkey revealed on spend | Deferred | 1.0× |
| P2TR | Tweaked Schnorr key revealed on spend | Deferred | **1.0×** |

P2TR uses full weight (previous 0.5× discount removed — tweaked Schnorr key offers no quantum hardness). Spend velocity captured separately by `SPEND_FREQUENCY_FACTOR["P2TR"]`.

---

## Project Structure

```
simulator/
  core/
    engine.py                DESEngine: heapq event loop, NIC contention, Turbine/routing
    phase2_engine.py         Phase2Engine: Poisson arrivals, mempool, fee market, agent model
    events.py                Event types and priority ordering
  network/
    node.py                  Node model: CPU min-heap scheduling, NIC bandwidth sharing
    topology.py              Network topology with geographic latency matrix
    propagation.py           Block/Transaction dataclasses, nearest-rank percentile
    routing.py               TurbineRouting, CompactBlockRouting (PQC-aware), EthHybridRouting
  mempool/
    mempool.py               Bounded mempool with fee-rate eviction
    algorithm_mix.py         PQC/classical algorithm sampling + Poisson arrival model
  chains/
    base.py                  Chain configs (Solana, Bitcoin, Ethereum)
    bitcoin_specific.py      UTXO tx model: BIP 141-correct SegWit weight accounting
    bitcoin_vulnerability.py Quantum exposure model: P2PK/P2PKH/P2TR, CRQC timeline
    ethereum_specific.py     EIP-7623 gas model, dual-sig AA, single calldata constant
    solana_specific.py       CU costs (Falcon > ML-DSA verified ordering), Gulf Stream
  economics/
    fee_market.py            Dynamic fee markets (EIP-1559, first-price, priority fee)
    block_builder.py         Priority block construction; verification_cost_weight censorship
    tx_viability.py          compute_tx_type_viability(), viability_sweep() — all 3 chains
    user_agents.py           5 archetypes; fee elasticity, batching, L2 migration
    validator_economics.py   Break-even stale rate, exit probability, network shrinkage
  calibration/
    baseline.py              NaN guard, per-metric tolerances
    mainnet_data.py          Hardcoded mainnet observations
  models/
    bandwidth.py             VALIDATOR_TIERS + SOLANA_VALIDATOR_TIERS (300 Mbps floor)
    latency.py               Log-normal jitter, geographic latency matrix
  results.py                 SimulationResult dataclass (stale_rate, demand_*, coverage)
  state.py                   Simulation state: event queue, block registry

blockchain/
  chain_models.py            Solana/Bitcoin/Ethereum throughput; compare_all_solana()
                             defaults to vote_tx_pct=0.70 (realistic)
  verification.py            VERIFICATION_PROFILES: Falcon batch_speedup=0.65;
                             SLH-DSA f/s inline labels; conservative 3× PQC margins
  aggregation.py             BLS, Falcon Merkle Tree, ML-DSA batch models

pqc_lib/
  signatures.py              ML-DSA, SLH-DSA, Falcon, Ed25519, ECDSA, Schnorr + hybrids
  kem.py                     ML-KEM (FIPS 203)
  mock.py                    NIST-accurate size mocks (no liboqs required when MOCK_PQC=1)

app/
  pqc_demo_streamlit.py      Main Streamlit orchestrator
  tabs/                      Overview, Algorithms, Block Space, PQC Shock, Viability, ...

tests/                       942 tests (pytest, MOCK_PQC=1)
  test_phase_b/              NIC contention, routing strategies
  test_phase_g/              Fee market, validator economics, calibration, vote overhead
  test_phase2/               Mempool, Phase 2 engine, Poisson arrivals
  test_chain_analysis/       BTC analysis, ETH analysis, migration model
  test_simulator/            Engine, latency, topology
  + 15 top-level test files  (see Running Tests section)

results/
  pqc_sweep.csv                Original 210-run Monte Carlo sweep
  solana_sweep_enhanced.csv    Enhanced Solana sweep (5 seeds × 21 PQC levels)
  sensitivity_falcon.csv       Falcon-dominant sensitivity (210 runs)
  sensitivity_mldsa_only.csv   ML-DSA-only sensitivity (210 runs)

ASSUMPTIONS_AND_LIMITATIONS.md  11 sections; 60+ documented assumptions,
                                 known limitations, and fix history
```

---

## Signature Algorithms

| Algorithm | Standard | Sig (B) | PK (B) | Verify (µs) | Batch speedup | NIST Level |
|-----------|----------|---------|--------|-------------|---------------|------------|
| Ed25519 | RFC 8032 | 64 | 32 | 60 | 0.5× | — |
| ECDSA | FIPS 186 | 72 | 33 | 80 | — | — |
| Schnorr (BIP 340) | BIP 340 | 64 | 32 | 60 | 0.4× | — |
| BLS12-381 | — | 96 | 48 | 1,500 | — | — |
| Falcon-512 | FN-DSA (pending) | 666 | 897 | 250 | **0.65×** | 1 |
| Falcon-1024 | FN-DSA (pending) | 1,280 | 1,793 | 400 | **0.65×** | 5 |
| ML-DSA-44 | FIPS 204 | 2,420 | 1,312 | 180 | — | 2 |
| ML-DSA-65 | FIPS 204 | 3,309 | 1,952 | 300 | — | 3 |
| ML-DSA-87 | FIPS 204 | 4,627 | 2,592 | 500 | — | 5 |
| SLH-DSA-128s | FIPS 205 | 7,856 | 32 | 2,160 | — | 1 |
| SLH-DSA-128f¹ | FIPS 205 | 17,088 | 32 | 5,940 | — | 1 |
| SLH-DSA-256s | FIPS 205 | 29,792 | 64 | 8,640 | — | 5 |
| SLH-DSA-256f¹ | FIPS 205 | 49,856 | 64 | 14,850 | — | 5 |

¹ **SLH-DSA "f" = fast signing, slow verification.** Counter-intuitive: `SLH-DSA-128f` verifies 2.75× slower than `SLH-DSA-128s`. Falcon's advantage is signature size, not verification speed — Falcon-512 verifies slower than ML-DSA-44 on the same hardware.

Verification times include 2.5–3.3× conservative safety margins over AVX2 OQS benchmarks (accounting for ARM validators, portable C, and OS jitter).

---

## Key Assumptions & Limitations

A full transparency disclosure is in [`ASSUMPTIONS_AND_LIMITATIONS.md`](ASSUMPTIONS_AND_LIMITATIONS.md) (11 sections, 60+ items). Critical highlights:

- **Solana DES is a 75-node scaled model** (mainnet: ~2,300 validators). Propagation dynamics scale linearly; absolute P90 values would shift at production scale.
- **Turbine is modelled as bounded-random gossip**, not a deterministic shred tree. Bandwidth concentration at layer-0 nodes is not captured; propagation coverage and hop count are correct.
- **Compact block efficiency degrades with PQC adoption** — modelled as `compact_fraction = 0.10 + 0.90 × pqc_fraction`. At 100% PQC, relay nodes transmit full blocks.
- **P2TR quantum exposure = 1.0×** (same as P2WPKH). Tweaked Schnorr keys provide no quantum hardness; Shor's algorithm recovers the secret key from Q = P + H(P,t)·G at identical cost. Source: [Google Quantum AI](https://research.google/blog/safeguarding-cryptocurrency-by-disclosing-quantum-vulnerabilities-responsibly/).
- **CRQC probability** uses a logistic CDF (symmetric), not the log-normal (right-skewed) distribution recommended by Mosca 2022. The logistic underestimates the probability of a late-but-sudden CRQC arrival.
- **No fork-choice or consensus** modelled. Stale rate is a proxy for orphaning risk, not actual orphan count.
- **All sweep CSVs pre-date several bug fixes** (fanout override, compact block efficiency, P2TR weight). Results are directionally correct; re-running experiments with the corrected engine will yield updated figures.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_PQC` / `PQC_MOCK` | `0` | Set to `1` to run without liboqs (NIST-accurate sizes, no crypto) |

---

## Author

**Shahbaz Zulkernain**  
MPhys Physics, University of St Andrews (Class of 2028)  
St Andrews Blockchain Society — PQC Research Lead
