# Assumptions and Limitations

This document catalogues every assumption, simplification, and known limitation in the PQC Cross-Chain Simulator. It is intended as a transparency disclosure for academic evaluation.

---

## 1. Network Model

### 1.1 Scaled Network Size
**Assumption:** The sweep uses 75 nodes (50 validators + 25 full nodes) and 10-second simulation runs, compared to Solana mainnet's ~795 validators and ~1,300 full nodes.

**Justification:** This is a standard discrete-event simulation trade-off. The propagation topology scales linearly with node count, and the per-hop delay model is independent of network size. The qualitative dynamics (block size → propagation delay → stale rate) are preserved, though absolute percentile values would shift with a larger network.

### 1.2 No Bandwidth Contention
**Simplification:** Propagation delays use a static formula (`latency + block_size / min(upload, download)`) rather than a queuing model. Simultaneous gossip transmissions from a single node each receive the full bandwidth independently — the NIC is not shared.

**Impact:** This underestimates real-world propagation delays, making the simulator's conclusions more conservative (actual network degradation under PQC would be worse than modelled).

**Note:** The `Node` class originally included SimPy Container resources for bandwidth queuing (`_upload_bw`, `_download_bw`) and SimPy Resource for CPU contention (`_cpu`), along with generator methods (`send_block()`, `verify_block()`) designed for process-based simulation. These were removed during the code cleanup as they were never invoked by the event-loop engine. The engine uses a deterministic analytical model (min-heap CPU scheduling, static bandwidth formula) rather than a process-based discrete-event simulation. A future extension could reintroduce SimPy for full queuing-theory fidelity.

### 1.3 Gossip Fanout Override — FIXED
**Status: Resolved.** The engine previously used a default gossip fanout of 8 that always overrode chain-specific values due to a truthiness bug (`config.gossip_fanout or chain_config.gossip_fanout` evaluated to 8 because 8 is truthy). This has been corrected: the engine default is now 0, and the guard uses `if config.gossip_fanout` so that chain-specific fanout values (e.g., Solana's 200) take effect when configured.

**Historical note:** Prior sweep results generated before this fix used fanout 8 for all chains. Regenerating the sweep CSV (`python run_experiments.py`) is recommended to incorporate the corrected fanout logic.

### 1.4 Fixed Jitter Model
**Simplification:** The engine uses a fixed coefficient of variation (CV = 0.15) for latency jitter on all routes, regardless of geographic distance. A more physically motivated distance-dependent CV model exists in `simulator/models/latency.py` but is only exercised in tests, not by the main simulation.

### 1.5 P90 Coverage Caveat
**Simplification:** The P90 propagation metric is computed over whichever nodes have received the block within the simulation window. If only 60% of nodes receive a block (e.g., at very high PQC fractions), the P90 is the 90th percentile of that 60%, not the full network — potentially flattering the result in edge cases.

### 1.6 Off-by-One in Percentile Calculation
**Known issue:** `propagation_percentile()` computes `index = int(N * p/100)`, which returns the `ceil` percentile rather than `floor`. For P90 with N=100, this gives the 91st element. The result is a mild systematic overestimate of propagation times at all percentiles. At small N (e.g., N=50 validators), the bias is more significant.

---

## 2. Transaction and Block Model

### 2.1 Algorithm Mix
**Default assumption:** The PQC algorithm mix is ML-DSA-44 (30%), ML-DSA-65 (50%), SLH-DSA-128f (20%). This is an arbitrary but plausible assumption — no blockchain has deployed PQC at scale, so there is no empirical distribution.

**Sensitivity tested:** Two alternative mixes were tested (Falcon-dominant 70/20/10 and ML-DSA-only 60/40/0) via 420 additional Monte Carlo runs. The sensitivity analysis (Section 4.8 of the report) shows that the algorithm mix is the single most consequential design variable.

### 2.2 Transaction Size
**Calculation:** Each transaction's size is `base_tx_overhead + signature_size + public_key_size`. This is consistent across the Phase 2 DES simulation and the static block-space analysis for all three chains.

**Note on Solana:** The Solana `base_tx_overhead` is set to 250 bytes, which models a single-instruction transfer transaction. Real Solana transactions vary widely (vote transactions, multi-instruction transactions, etc.).

### 2.3 Single Signature Per Transaction
**Assumption:** Each transaction contains exactly one signature. Multi-signature transactions, threshold signatures, and account abstraction schemes are not modelled. This is a simplification — Bitcoin's P2SH and Ethereum's smart contract wallets can require multiple signatures per transaction.

### 2.4 No Adaptive Block Sizes
**Simplification:** Block sizes are fixed at the chain's static limit (6 MB for Solana, 4 MWU for Bitcoin, gas-limited for Ethereum). No dynamic block size adjustment is modelled. Real protocols may adopt adaptive block sizing to accommodate PQC transaction bloat.

### 2.5 Solana MTU Constraint (1,232 Bytes)
**Known limitation:** Solana enforces a maximum transmission unit (MTU) of 1,232 bytes per transaction packet (derived from IPv6 minimum MTU of 1,280 bytes minus 48 bytes of headers). Several PQC algorithms produce signatures that, combined with the transaction overhead, exceed this limit:

| Algorithm | Sig + PK + Overhead | Exceeds 1,232 B? |
|-----------|-------------------|-------------------|
| ML-DSA-44 | 2,584 + 1,312 + 250 = 4,146 B | Yes (3.4×) |
| ML-DSA-65 | 3,309 + 1,952 + 250 = 5,511 B | Yes (4.5×) |
| SLH-DSA-128f | 17,088 + 32 + 250 = 17,370 B | Yes (14.1×) |
| Falcon-512 | 666 + 897 + 250 = 1,813 B | Yes (1.5×) |

**Impact:** Deploying any NIST PQC algorithm on Solana would require a protocol-level MTU increase or a signature compression scheme. The simulator models block-level capacity impact but does not enforce the per-transaction MTU constraint. A warning box is displayed in the Block Space Analysis tab when Solana is selected.

**Note:** This is a fundamental protocol constraint, not a simulator limitation — no current PQC signature fits within Solana's packet size.

---

## 3. Verification Timing Model

### 3.1 Verification Time Sources
**Source:** All verification times are derived from wolfSSL benchmarks (wolfCrypt, 2025) with conservative safety margins:

| Algorithm | wolfSSL (µs) | Simulator (µs) | Margin |
|-----------|-------------|----------------|--------|
| Ed25519 | 44 | 60 | 1.36× |
| ML-DSA-44 | 166 | 550 | 3.3× |
| ML-DSA-65 | 265 | 940 | 3.5× |
| ML-DSA-87 | 403 | 1,500 | 3.7× |
| SLH-DSA-128f | ~1,500 | 5,940 | ~4.0× |
| Falcon-512 | ~70 | 245 | 3.5× |

**Asymmetric margins:** PQC algorithms use 3–4× margins (accounting for unoptimised real-world implementations, validator hardware variance, and the relative immaturity of PQC software). Ed25519 uses a modest 1.36× margin (mature, heavily optimised implementations). This asymmetry is a deliberate design choice that makes PQC look relatively worse versus classical — the intent is conservative (worst-case) modelling.

### 3.2 SLH-DSA Scaling
**Derivation:** SLH-DSA-192f is set to 1.5× of SLH-DSA-128f (8,910 µs) and SLH-DSA-256f to 2.5× of SLH-DSA-128f (14,850 µs), reflecting the scaling of hash tree evaluations with security level. Exact ratios are not well-established in the literature and should be treated as estimates.

### 3.3 Analytical CPU Scheduling
**Simplification:** The CPU scheduling model uses an analytical min-heap: each CPU core tracks when it becomes free, and new verification tasks are assigned to the earliest-available core. This approximates a non-preemptive M/G/c queue without modelling OS scheduling overhead, context switches, or cache effects.

### 3.4 ML-DSA Batch Verification
**Inconsistency:** `blockchain/aggregation.py` models ML-DSA batch verification with a 40% speedup factor (`verification_time_factor = 0.6`). `blockchain/verification.py` assigns ML-DSA profiles a batch speedup of 1.0 (no speedup). These two modules serve different analysis paths and give contradictory answers for batch verification efficiency. The DES simulation uses `verification.py` (no batch speedup).

---

## 4. Baseline Calibration

### 4.1 Simulator vs Mainnet
At 0% PQC adoption, the simulator produces a mean stale rate of 0.0% with a P90 propagation delay of 215 ms (53.8% of the 400 ms slot). By comparison, Solana mainnet's observed slot skip rate during 2024–2025 is approximately 5%.

**Why the difference:** The simulator intentionally isolates the PQC signature-size channel by holding all other factors constant. The mainnet skip rate reflects additional real-world factors: validator software bugs, consensus voting overhead, leader rotation latency, clock drift, and transient network partitions — none of which relate to signature size or verification time.

### 4.2 Propagation Model Validation
The 215 ms P90 baseline is consistent with Decker and Wattenhofer's empirical propagation model (IEEE P2P, 2013) for ~70 KB blocks on a 75-node network with heterogeneous bandwidth.

---

## 5. Cross-Chain Extrapolation

### 5.1 Solana-Only DES Simulation
The Monte Carlo DES simulation (sweep CSV, sensitivity CSVs) was only run for a Solana-like chain. Bitcoin and Ethereum estimates in the PQC Shock Simulator tab are first-order analytical extrapolations, not separate DES simulations. They scale the Solana results by relative block time, block size, and propagation differences.

### 5.2 "Cross-Chain" Title
The project title "PQC Cross-Chain Simulator" is somewhat misleading: the DES simulation is single-chain (Solana-parametrised). The "cross-chain" aspect comes from the static block-space analysis (which is exact per chain) and the analytical extrapolation (which is approximate). A more precise title would be "PQC Blockchain Impact Simulator with Cross-Chain Block-Space Analysis."

---

## 6. Ethereum Gas Model

### 6.1 Gas Limit Assumptions
The model uses the following Ethereum gas limits:
- **Current:** 60,000,000 (60M gas, as of early 2026)
- **2026 target:** 100,000,000 (100M gas, per Vitalik's roadmap)
- **Long-term:** 200,000,000 (200M gas)

These are subject to change as Ethereum's gas limit is governed by validator voting, not a fixed schedule.

### 6.2 Calldata vs Blob Data
The Ethereum model uses calldata-based gas costing (16 gas/byte for non-zero data). EIP-4844 blob transactions (128 KB ephemeral data per blob) are not modelled. Blob transactions could significantly reduce the effective cost of PQC signatures if used for signature aggregation proofs.

---

## 7. Scope Limitations

### 7.1 No Fork Choice / Consensus
The simulator models block propagation and stale rates but does not implement a fork-choice rule. All proposed blocks are assumed to be valid (no invalid block rejection, no competing forks, no longest-chain selection). The "stale rate" is defined as the fraction of blocks whose P90 propagation exceeds 90% of the block time — a proxy for orphaning risk, not actual orphan count.

### 7.2 No Economic Modelling
Validator economics (block rewards, MEV, operating costs) are not modelled. The stale rate is used as a proxy for economic pressure on validators: at 30%+ stale rates, validators lose ~1 in 3 blocks, which would drive exit of marginal operators. This centralisation dynamic is discussed qualitatively but not simulated.

### 7.3 No Hardware Acceleration
The verification timing model assumes software-only implementations. Dedicated hardware (FPGAs, ASICs) can achieve 8–300× acceleration for PQC verification (e.g., SLotH FPGA for SLH-DSA achieves 300× speedup). The timeline for hardware deployment versus Q-Day is an open question.

### 7.4 pqc_lib Decoupled from DES Engine
The `pqc_lib/` package provides actual cryptographic operations (or NIST-accurate mocks) for the Streamlit UI demo. It is **not** used by the DES simulation engine, which uses hardcoded signature sizes from `blockchain/chain_models.py` and verification times from `blockchain/verification.py`. The two systems use the same NIST-standard sizes but are independent code paths.

### 7.5 Signature Aggregation Not in Simulation
`blockchain/aggregation.py` models BLS, Falcon Merkle Tree, and ML-DSA batch verification schemes analytically. These are not integrated into the DES simulation or the Streamlit UI — they exist as a standalone analysis module.

### 7.6 No Turbine Modelling (Solana)
**Limitation:** Solana's Turbine protocol (erasure-coded block sharding across neighbourhood trees) is not modelled. The simulator uses a flat gossip propagation model where each node forwards the full block to `fanout` peers. In practice, Turbine distributes ~64 KB "shreds" in a tree structure, which dramatically reduces per-node bandwidth requirements and propagation latency for large blocks.

**Impact:** The simulator overestimates propagation delays for Solana at high PQC adoption (large blocks), because the flat-gossip model requires each node to transmit and receive the full block. Turbine's shredding would partially offset the block-size inflation from PQC signatures. This makes the simulator's Solana projections conservative — real-world degradation would likely be less severe than modelled, all else being equal.

---

## 8. Software Engineering Limitations

### 8.1 Sweep Data Coupling
The PQC Shock Simulator tab reads from `results/pqc_sweep.csv`. If the CSV is not present, the tab shows an error message directing the user to run `python run_experiments.py`. The CSV must be regenerated if any simulation parameter changes.

### 8.2 Mempool Eviction Performance
The mempool's eviction strategy scans for the lowest fee-rate transaction using a linear scan (O(n)). For large mempools (100k+ transactions), this could be a performance concern, though it does not affect correctness.

### 8.3 Calibration Module
`simulator/calibration/runner.py` and `simulator/calibration/targets.py` contain a calibration workflow that was used during Phase 1 development. They are not wired into the current automated pipeline and are preserved as utilities.
