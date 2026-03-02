# PQC Cross-Chain Simulator

A discrete-event simulation framework quantifying how post-quantum cryptography (PQC) signatures affect throughput, propagation, and stale rates in real blockchain networks — **Solana**, **Bitcoin**, and **Ethereum**.

## What This Project Does

Blockchains rely on digital signatures (Ed25519, ECDSA, Schnorr) that are vulnerable to quantum computers via Shor's algorithm. NIST-standardised PQC replacements (FIPS 204/205) are **10–267× larger** and verification is **3–100× slower**, directly reducing throughput. This simulator models that impact using:

1. **Static block-space analysis** — Per-chain throughput retention under each PQC algorithm, accounting for chain-specific structures (Solana vote overhead, Bitcoin SegWit discount, Ethereum gas costing).
2. **Monte Carlo DES simulation** — A 75-node network (50 validators + 25 full nodes) with Poisson transaction arrivals, bounded mempool with fee-rate eviction, heterogeneous signature blocks, and per-transaction verification timing. Sweeps across 0–100% PQC adoption (21 levels × 10 seeds = 210 runs).
3. **Sensitivity analysis** — Additional 420 runs testing Falcon-dominant and ML-DSA-only algorithm mixes to quantify the impact of the signature composition.

### Key Finding

At ~37% PQC adoption (default 30/50/20 mix of ML-DSA-44/ML-DSA-65/SLH-DSA-128f), the network crosses a catastrophic threshold: mean stale rate exceeds 30%, block sizes reach 10.4× baseline, and propagation P90 consumes 95% of the 400 ms slot. The bottleneck is **bandwidth (block bloat), not compute (verification time)** — verification uses only ~16% of the slot even at 100% PQC.

### UI Tabs

- **Overview** — Cross-chain throughput retention heatmap, per-chain summaries, quantum threat context
- **Algorithms** — Side-by-side keygen/sign/verify comparison across all algorithms
- **Block Space** — Per-chain throughput impact with adjustable parameters (Solana vote overhead, Bitcoin SegWit discount, Ethereum gas limits)
- **PQC Shock Simulator** — Monte Carlo sweep visualisation: Death Curve (stale rate), Block Bloat, False Bottleneck (verification), cross-chain extrapolation

## Quick Start

### With Docker (recommended)

```bash
docker compose up --build
# Open http://localhost:8501
```

### Mock mode (no liboqs needed)

```bash
docker compose --profile mock up --build
# Open http://localhost:8502
```

### Local development

```bash
pip install -r requirements.txt

# Run the Monte Carlo sweep first (generates results/pqc_sweep.csv):
python run_experiments.py

# Then launch the UI:
PQC_MOCK=1 streamlit run app/pqc_demo_streamlit.py
```

## Running Tests

```bash
# Mock mode (always works, no liboqs required)
PQC_MOCK=1 pytest tests/ -v

# With liboqs
pytest tests/ -v
```

## Running Benchmarks (CLI)

```bash
python -m benchmarks.bench
# Results written to benchmarks/results/benchmark_results.csv
```

## Running Sensitivity Sweeps

```bash
python run_sensitivity_sweeps.py            # Both Falcon-dominant + ML-DSA-only
python run_sensitivity_sweeps.py --sweep falcon      # Falcon-dominant only
python run_sensitivity_sweeps.py --sweep mldsa_only  # ML-DSA-only only
python analyze_sensitivity.py               # Compare all three mixes
```

## Project Structure

```
simulator/                  Discrete-event simulation engine
  core/
    engine.py               Phase 1 DES engine (propagation model)
    phase2_engine.py        Phase 2/3 engine (Poisson arrivals, mempool, heterogeneous blocks)
    events.py               Event types and priority ordering
  network/
    node.py                 Node model with CPU scheduling (analytical min-heap)
    topology.py             Network topology with geographic latency matrix
    propagation.py          Block and Transaction dataclasses, percentile computation
  mempool/
    mempool.py              Bounded mempool with fee-rate eviction
    algorithm_mix.py        PQC/classical algorithm sampling + Poisson arrival model
  models/
    bandwidth.py            Validator/full-node hardware tier sampling
    latency.py              Latency model (distance-dependent, used in tests)
  chains/
    base.py                 Chain configurations (Solana, Bitcoin, Ethereum)
  calibration/
    runner.py               Calibration runner (utility, not in main pipeline)
    targets.py              Calibration targets and AWS Cloudping reference data
  state.py                  Simulation state (event queue, block registry)
  results.py                Result dataclasses

blockchain/                 Blockchain impact modelling
  chain_models.py           Solana, Bitcoin, Ethereum block-space analysis
  verification.py           Signature verification time profiles
  aggregation.py            Signature aggregation scheme models (BLS, Falcon tree, ML-DSA batch)

pqc_lib/                    PQC algorithm wrappers (used by UI and benchmarks, not DES engine)
  signatures.py             ML-DSA, SLH-DSA, Falcon, Ed25519, ECDSA, Schnorr + hybrids
  kem.py                    ML-KEM (FIPS 203): keygen, encaps, decaps
  mock.py                   Deterministic mocks with NIST-accurate artifact sizes
  utils.py                  Timing and memory profiling utilities

app/                        Streamlit application
  pqc_demo_streamlit.py     Main orchestrator (sidebar, tabs, chain context)
  tabs/
    overview.py             Tab 1: Cross-chain overview with throughput heatmap
    comparison.py           Tab 2: Side-by-side algorithm comparison
    block_space.py          Tab 3: Block-space visualiser with adjustable parameters
    pqc_shock_sim.py        Tab 4: PQC Shock Simulator (Monte Carlo sweep charts)
  components/
    charts.py               Reusable Plotly chart builders
  utils.py                  Shared formatting utilities

run_experiments.py          Monte Carlo PQC fraction sweep (generates pqc_sweep.csv)
run_sensitivity_sweeps.py   Sensitivity analysis with alternative algorithm mixes
analyze_results.py          Summary analysis of sweep results
analyze_refined.py          Detailed failure-threshold analysis
analyze_sensitivity.py      Comparative analysis across three algorithm mixes
generate_pqc_report.py      PDF report generator (21-page academic report)

results/                    Sweep output CSVs
  pqc_sweep.csv             210 rows: default mix (30% ML-DSA-44, 50% ML-DSA-65, 20% SLH-DSA-128f)
  sensitivity_falcon.csv    210 rows: Falcon-dominant (70% Falcon-512, 20% ML-DSA-65, 10% SLH-DSA-128f)
  sensitivity_mldsa_only.csv 210 rows: ML-DSA-only (60% ML-DSA-44, 40% ML-DSA-65)

benchmarks/                 Benchmark harness
  bench.py                  CLI benchmark runner with CSV export

tests/                      Unit tests (pytest)

.github/workflows/ci.yml   GitHub Actions: test + lint on Python 3.10–3.12
docs/methodology.md         Methodology documentation
ASSUMPTIONS_AND_LIMITATIONS.md  All assumptions, simplifications, and known limitations
```

## Signature Algorithms

| Algorithm | Type | Standard | Sig Size | PK Size | NIST Level |
|-----------|------|----------|----------|---------|------------|
| Ed25519 | Classical | RFC 8032 | 64 B | 32 B | N/A |
| ECDSA | Classical | FIPS 186 | 72 B | 33 B | N/A |
| Schnorr | Classical | BIP 340 | 64 B | 32 B | N/A |
| ML-DSA-44 | PQC | FIPS 204 | 2,420 B | 1,312 B | 2 |
| ML-DSA-65 | PQC | FIPS 204 | 3,309 B | 1,952 B | 3 |
| ML-DSA-87 | PQC | FIPS 204 | 4,627 B | 2,592 B | 5 |
| Falcon-512 | PQC | Pending (FN-DSA) | 666 B | 897 B | 1 |
| Falcon-1024 | PQC | Pending (FN-DSA) | 1,280 B | 1,793 B | 5 |
| SLH-DSA-128s | PQC | FIPS 205 | 7,856 B | 32 B | 1 |
| SLH-DSA-128f | PQC | FIPS 205 | 17,088 B | 32 B | 1 |

## Blockchain Models

| Chain | Baseline Sig | Block Limit | Block Time | Key Feature |
|-------|-------------|-------------|------------|-------------|
| Solana | Ed25519 | ~6 MB | 400 ms | Vote tx overhead (70–80%), gossip propagation |
| Bitcoin | ECDSA/Schnorr | 4 MWU | 10 min | SegWit witness discount (1/4 weight) |
| Ethereum | ECDSA | 60M gas (current) | 12 s | Gas-based costing, roadmap targets 100M+ |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PQC_MOCK` | `0` | Set to `1` to force mock mode (no liboqs needed) |

## Author

**Shahbaz Zulkernain**
MPhys Physics, University of St Andrews (Class of 2028)
St Andrews Blockchain Society — PQC Research Lead
