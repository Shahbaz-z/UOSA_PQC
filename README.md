# PQC Cross-Chain Simulator

A cross-chain simulator quantifying how post-quantum cryptography (PQC) signatures change security, decentralisation, and fees in real blockchain networks -- **Solana**, **Bitcoin**, and **Ethereum**.

## What This Project Does

Blockchains rely on digital signatures (Ed25519, ECDSA, Schnorr) that are vulnerable to quantum computers via Shor's algorithm. PQC signatures are **10-700x larger** and verification is **2-50x slower**, directly reducing throughput. This simulator models that impact across three major blockchains, including verification time bottlenecks and signature aggregation strategies.

### Features

- **Block-Space Visualizer** -- Per-chain throughput impact analysis with adjustable parameters (Solana vote overhead, Bitcoin SegWit discount, Ethereum gas limits 30M-180M)
- **Side-by-Side Comparison** -- Compare keygen/sign/verify across multiple algorithms
- **Cross-Chain Summary** -- Compare PQC migration impact across all three blockchains
- **Verification Time Modeling** -- Identifies whether block space or signature verification is the throughput bottleneck
- **Signature Aggregation** -- Models BLS, Falcon Merkle Tree, and ML-DSA batch verification schemes
- **Mock Mode** -- Runs without liboqs; artifact sizes remain NIST-accurate, timing is synthetic
- **Benchmark Harness** -- CLI timing and memory profiling with CSV export

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

# With liboqs installed:
streamlit run app/pqc_demo_streamlit.py

# Without liboqs (mock mode):
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

## Project Structure

```
pqc_lib/                PQC algorithm wrappers
  kem.py                ML-KEM (FIPS 203): keygen, encaps, decaps
  signatures.py         ML-DSA, SLH-DSA, Falcon, Ed25519, ECDSA, Schnorr + hybrids
  mock.py               Deterministic mocks with NIST-accurate artifact sizes
  utils.py              Timing and memory profiling utilities

blockchain/             Blockchain impact modeling
  chain_models.py       Solana, Bitcoin, and Ethereum block-space analysis
  verification.py       Signature verification time modeling
  aggregation.py        Signature aggregation scheme models

app/                    Streamlit application
  pqc_demo_streamlit.py Main orchestrator (sidebar, page config, tab setup)
  tabs/                 Per-tab rendering modules
    block_space.py      Tab 1: Block-Space Visualizer
    comparison.py       Tab 2: Side-by-Side Comparison
    cross_chain.py      Tab 3: Cross-Chain Summary
  components/
    charts.py           Reusable Plotly chart builders

benchmarks/             Benchmark harness and results
  bench.py              CLI benchmark runner with CSV export

tests/                  Unit tests (pytest)
  test_signatures.py    Signature algorithm tests
  test_kem.py           KEM algorithm tests
  test_solana_model.py  Blockchain model tests (all 3 chains + input validation)
  test_verification.py  Verification time model tests
  test_aggregation.py   Aggregation scheme tests
  test_charts.py        Chart function tests
  test_ui_integration.py Streamlit app integration tests

.github/workflows/      CI/CD
  ci.yml                GitHub Actions: test + lint on Python 3.10-3.12

docs/                   Methodology documentation
```

## Signature Algorithms

| Algorithm | Type | Standard | Sig Size | PK Size | NIST Level |
|-----------|------|----------|----------|---------|------------|
| Ed25519 | Classical | RFC 8032 | 64 B | 32 B | N/A |
| ECDSA | Classical | FIPS 186 | 72 B | 33 B | N/A |
| Schnorr | Classical | BIP 340 | 64 B | 32 B | N/A |
| ML-DSA-44 | PQC | FIPS 204 | 2,420 B | 1,312 B | 2 |
| ML-DSA-65 | PQC | FIPS 204 | 3,293 B | 1,952 B | 3 |
| ML-DSA-87 | PQC | FIPS 204 | 4,595 B | 2,592 B | 5 |
| Falcon-512 | PQC | Pending (FN-DSA) | 666 B | 897 B | 1 |
| Falcon-1024 | PQC | Pending (FN-DSA) | 1,280 B | 1,793 B | 5 |
| SLH-DSA-128s | PQC | FIPS 205 | 7,856 B | 32 B | 1 |
| SLH-DSA-128f | PQC | FIPS 205 | 17,088 B | 32 B | 1 |

## Blockchain Models

| Chain | Baseline Sig | Block Limit | Block Time | Key Feature |
|-------|-------------|-------------|------------|-------------|
| Solana | Ed25519 | ~6 MB | 400 ms | Vote tx overhead (70-80%) |
| Bitcoin | ECDSA/Schnorr | 4 MWU | 10 min | SegWit witness discount (1/4 weight) |
| Ethereum | ECDSA | 30M gas (2024) | 12 s | Gas-based costing, 2026 increases to 180M |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PQC_MOCK` | `0` | Set to `1` to force mock mode (no liboqs needed) |
