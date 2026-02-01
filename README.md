# UOSA PQC – Post-Quantum Cryptography Demo

Interactive demonstration of NIST post-quantum cryptographic algorithms and their impact on Solana blockchain throughput.

## Features

- **KEM Demo** – Kyber512/768/1024 key encapsulation with interactive keygen, encapsulate, decapsulate
- **Signature Demo** – Dilithium2/3/5, Ed25519, and hybrid (Ed25519+Dilithium) signing and verification
- **Block-Space Visualizer** – Solana throughput impact analysis with adjustable parameters
- **Benchmark Harness** – Timing and memory profiling with CSV export
- **Mock Mode** – Runs without liboqs for easy hosting/demo (artifact sizes remain accurate)

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
# Mock mode (always works)
PQC_MOCK=1 pytest

# With liboqs
pytest
```

## Running Benchmarks (CLI)

```bash
python -m benchmarks.bench
# Results written to benchmarks/results/benchmark_results.csv
```

## Project Structure

```
pqc_lib/          PQC algorithm wrappers (Kyber, Dilithium, Ed25519)
  kem.py          Kyber KEM: keygen, encaps, decaps
  signatures.py   Dilithium + Ed25519 + hybrid signatures
  mock.py         Deterministic mocks with correct artifact sizes
  utils.py        Timing and memory profiling utilities

benchmarks/       Benchmark harness and results
  bench.py        CLI benchmark runner with CSV export

blockchain/       Blockchain impact modeling
  solana_model.py Solana block-space analysis

app/              Streamlit application
  pqc_demo_streamlit.py   Main app (3 tabs)
  components/             Reusable chart builders

tests/            Unit tests (pytest)
docs/             Methodology documentation
```

## Algorithms

| Algorithm | Type | Key Size | Signature/CT Size | NIST Level |
|-----------|------|----------|-------------------|------------|
| Kyber512 | KEM | 800 B | 768 B | 1 |
| Kyber768 | KEM | 1184 B | 1088 B | 3 |
| Kyber1024 | KEM | 1568 B | 1568 B | 5 |
| Dilithium2 | Sig | 1312 B | 2420 B | 2 |
| Dilithium3 | Sig | 1952 B | 3293 B | 3 |
| Dilithium5 | Sig | 2592 B | 4595 B | 5 |
| Ed25519 | Sig | 32 B | 64 B | Classical |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PQC_MOCK` | `0` | Set to `1` to force mock mode |
