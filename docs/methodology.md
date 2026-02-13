# Methodology

This document describes the models and assumptions used by the Blockchain Quantum Resistance Educator.

## 1. Signature & KEM Parameters

All artifact sizes (public keys, secret keys, signatures, ciphertexts) match the NIST FIPS 203/204/205 specifications and Falcon round-3 submissions. In mock mode, timing is synthetic but sizes are accurate.

**Sources:**
- FIPS 203 (ML-KEM): Module-Lattice-Based Key-Encapsulation Mechanism
- FIPS 204 (ML-DSA): Module-Lattice-Based Digital Signature Algorithm
- FIPS 205 (SLH-DSA): Stateless Hash-Based Digital Signature Algorithm
- Falcon specification (pending FIPS as FN-DSA)

## 2. Blockchain Block-Space Models

### 2.1 Solana

**Model:** byte-based block capacity.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Block size | 6,000,000 B | Practical limit (~6 MB); theoretical max 32 MB |
| Base tx overhead | 250 B | Accounts, instructions, blockhash |
| Slot time | 400 ms | Target slot duration |
| Vote tx overhead | 0-85% | Validator vote transactions consuming block space |

**Transaction size** = base_overhead + (signature_bytes + public_key_bytes) × num_signers

**Txs per block** = (block_size × (1 - vote_pct)) ÷ tx_size

**Vote transaction modeling:** In production, 70-80% of Solana block space is consumed by validator vote transactions. The vote overhead parameter reduces available block capacity proportionally.

### 2.2 Bitcoin

**Model:** SegWit weight-based block capacity.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Block weight limit | 4,000,000 WU | BIP 141 weight limit (4 MWU) |
| Base tx overhead | 150 B | Version, locktime, inputs/outputs (non-witness) |
| Block time | 600,000 ms | Average 10 minutes |

**SegWit weight calculation (BIP 141):**
- Non-witness data (base overhead): **4 weight units per byte**
- Witness data (signatures + public keys): **1 weight unit per byte**

**Tx weight** = (base_overhead × 4) + (signature_bytes + public_key_bytes) × num_signers × 1

This discount means PQC signatures (which are all witness data) benefit from the 4:1 reduction. A 3,293-byte ML-DSA-65 signature costs 3,293 WU rather than 13,172 WU.

**Txs per block** = block_weight_limit ÷ tx_weight

### 2.3 Ethereum

**Model:** gas-based block capacity.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Block gas limit | 30,000,000 | 2024 baseline; roadmap targets up to 180M by 2026 |
| Base tx gas | 21,000 | Intrinsic transaction gas (EIP-2718) |
| Calldata gas | 16 gas/byte | Non-zero byte calldata cost |
| Base tx overhead | 120 B | Non-signature calldata (to, value, nonce, etc.) |
| Block time | 12,000 ms | Post-Merge slot time |

**Tx gas** = 21,000 + (base_overhead + signature_bytes + public_key_bytes) × num_signers × 16

**Gas limit roadmap modeled:**

| Period | Gas Limit |
|--------|-----------|
| 2024 baseline | 30,000,000 |
| 2025 current | 36,000,000 |
| 2026 Q1 | 60,000,000 |
| 2026 Q2 | 80,000,000 |
| 2026 target | 180,000,000 |

## 3. ZK Proof System Models

Models ZK-STARK and ZK-SNARK proof systems on Ethereum's gas model.

### 3.1 Proof Systems

| System | Family | Proof Size | Verification Gas | Quantum Resistant | Trusted Setup |
|--------|--------|-----------|-----------------|-------------------|---------------|
| Groth16 | SNARK | 128 B | 200,000 | No | Yes (per-circuit) |
| PLONK | SNARK | 560 B | 300,000 | No | Yes (universal) |
| Halo2 | SNARK | 4,800 B | 500,000 | No | No (IPA) |
| STARK-S | STARK | 45,000 B | 1,200,000 | Yes | No |
| STARK-L | STARK | 200,000 B | 5,000,000 | Yes | No |

**Tx gas for ZK proof** = 21,000 (base) + proof_bytes × 16 (calldata) + verification_gas

**Key distinction:**
- ZK-STARKs are hash-based and quantum-resistant
- ZK-SNARKs rely on elliptic-curve pairings vulnerable to Shor's algorithm

**Sources:**
- StarkWare documentation for STARK proof sizes
- Ethereum EIP-196/197 for bn128 precompile gas costs
- ethSTARK documentation for on-chain verification costs
- Groth16: 3 group elements on bn128 (~128 bytes)

### 3.2 Limitations

- Models single-proof-per-transaction (not batched rollup economics)
- Does not model recursive proof composition or proof aggregation
- Does not account for EIP-4844 blob-based data availability
- Verification gas costs are approximate (vary with circuit complexity)

## 4. Quantum Resistance (QR) Scoring Model

Produces a composite 0-100 score per blockchain across five weighted dimensions.

### 4.1 Dimensions and Weights

| Dimension | Weight | Scoring Method |
|-----------|--------|----------------|
| Throughput Retention | 30% | Best PQC algorithm's relative throughput × 100 |
| Migration Feasibility | 25% | Qualitative assessment (0-100) |
| Signature Size | 20% | max(0, 100 - 15 × log2(pqc_size / classical_size)) |
| ZK Readiness | 15% | Qualitative assessment (0-100) |
| Algorithm Diversity | 10% | 25 points per viable PQC family (>10% retention) |

### 4.2 Letter Grades

| Grade | Score Range |
|-------|------------|
| A | 85-100 |
| B | 75-84 |
| C | 60-74 |
| D | 45-59 |
| F | 0-44 |

### 4.3 Qualitative Scores

Migration feasibility and ZK readiness are qualitative assessments reflecting:
- **Migration Feasibility:** Account model (UTXO vs account), hard fork requirements, governance speed, existing PQC research
- **ZK Readiness:** Native ZK precompiles, active ZK rollup ecosystem, STARK verification feasibility

### 4.4 Limitations

- Qualitative scores encode expert judgment, not empirical measurements
- Does not model ecosystem readiness (wallet support, developer tooling)
- Does not predict governance velocity or economic migration incentives
- Algorithm diversity counts families, not the quality of implementations
- ZK readiness is Ethereum-centric (other chains have different L2 strategies)

## 5. Benchmark Methodology

### Timing
- Uses `time.perf_counter()` for high-resolution monotonic timing
- Each operation run N times (default: 5) after 1 warmup run
- Reports mean, stddev, min, max in milliseconds

### Memory
- Uses `tracemalloc` to measure Python heap allocations
- Reports peak allocation per operation in KB
- **Limitation:** Does not capture C-level allocations inside liboqs; numbers reflect Python-side overhead only

## 6. General Limitations

- All models are **static analysis** of protocol parameters, not real-world deployment simulations
- Transaction mix is homogeneous (all simple transfers); does not model DEX swaps, DeFi, NFTs
- Does not model verification time impact on block processing
- Does not model network propagation delays from larger transactions
- Does not account for compression techniques or signature aggregation
- Mock mode provides accurate sizes but synthetic timing
