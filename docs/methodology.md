# Methodology

This document describes the models and assumptions used by the PQC Cross-Chain Simulator.

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

**Transaction size** = base_overhead + (signature_bytes + public_key_bytes) x num_signers

**Txs per block** = (block_size x (1 - vote_pct)) / tx_size

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

**Tx weight** = (base_overhead x 4) + (signature_bytes + public_key_bytes) x num_signers x 1

This discount means PQC signatures (which are all witness data) benefit from the 4:1 reduction. A 3,293-byte ML-DSA-65 signature costs 3,293 WU rather than 13,172 WU.

**Txs per block** = block_weight_limit / tx_weight

### 2.3 Ethereum

**Model:** gas-based block capacity.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Block gas limit | 60,000,000 | Current baseline (as of early 2026); roadmap targets up to 180M |
| Base tx gas | 21,000 | Intrinsic transaction gas (EIP-2718) |
| Calldata gas | 16 gas/byte | Non-zero byte calldata cost |
| Base tx overhead | 120 B | Non-signature calldata (to, value, nonce, etc.) |
| Block time | 12,000 ms | Post-Merge slot time |

**Tx gas** = 21,000 + (base_overhead + signature_bytes + public_key_bytes) x num_signers x 16

**Gas limit roadmap modeled:**

| Period | Gas Limit |
|--------|-----------|
| 2024 baseline | 30,000,000 |
| 2025 mid-year | 36,000,000 |
| 2025 Q4 / 2026 Q1 | 60,000,000 |
| 2026 Q2 | 80,000,000 |
| 2026 target | 180,000,000 |

## 3. Verification Time Model

Models how long it takes to verify all signatures in a block, identifying whether verification time (not just block space) becomes the throughput bottleneck with PQC schemes.

### 3.1 Per-Algorithm Verification Times

| Algorithm | Verify Time (us) | Batch Speedup | Source |
|-----------|------------------|---------------|--------|
| Ed25519 | 60 | 0.5x (batch) | libsodium, dalek-cryptography |
| ECDSA | 80 | 1.0x | libsecp256k1 |
| Schnorr | 60 | 0.4x (MuSig) | libsecp256k1 |
| ML-DSA-44 | 180 | 1.0x | liboqs (AVX2) |
| ML-DSA-65 | 300 | 1.0x | liboqs (AVX2) |
| ML-DSA-87 | 500 | 1.0x | liboqs (AVX2) |
| Falcon-512 | 100 | 1.0x | liboqs (fast verify) |
| Falcon-1024 | 200 | 1.0x | liboqs |
| SLH-DSA-128s | 3,000 | 1.0x | liboqs (hash-heavy) |
| SLH-DSA-128f | 5,940 | 1.0x | liboqs (hash-heavy) |
| SLH-DSA-256f | 2,000 | 1.0x | liboqs |

### 3.2 Block Verification Model

**Serial time** = verify_time_us x txs_per_block / 1000 (ms)

**Parallel time** = serial_time / num_cores (if parallelizable)

**Effective TPS** = min(block_space_TPS, verification_limited_TPS)

**Bottleneck** = whichever limit is lower determines the actual throughput.

### 3.3 Key Insight

Falcon-512 has verification times close to Ed25519 (100us vs 60us), making it the best PQC option for verification-limited chains like Solana. SLH-DSA variants (3-8ms per verify) create severe verification bottlenecks on all chains.

## 4. Signature Aggregation Model

Models how aggregation techniques reduce per-transaction signature overhead.

### 4.1 Aggregation Schemes

| Scheme | Sig Size Formula | PK Size Formula | Verify Factor | QR? |
|--------|-----------------|-----------------|---------------|-----|
| None | sig x n | pk x n | 1.0x | depends |
| BLS (BLS12-381) | 48 B (constant) | 48 x n | 1.5x | No |
| Falcon Merkle Tree | sig + 32 x log2(n) | 32 B (root) | 1.2x | Yes |
| ML-DSA Batch | sig x n (no reduction) | pk x n | 0.6x | Yes |

### 4.2 Key Insights

- **BLS** offers the best compression (constant 48B) but is NOT quantum-resistant
- **Falcon-Tree** provides >90% size reduction at batch=100 while remaining quantum-resistant
- **ML-DSA-Batch** doesn't reduce size but speeds up verification by ~40%
- Aggregation is most impactful on chains where block space is the bottleneck (Solana, Bitcoin)

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
- Does not model network propagation delays from larger transactions
- Does not account for compression techniques beyond the modeled aggregation schemes
- Mock mode provides accurate sizes but synthetic timing
- Verification times are representative benchmarks, not measured on the user's hardware
