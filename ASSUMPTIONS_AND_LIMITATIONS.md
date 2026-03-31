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

### 1.3 Gossip Fanout Override — FIXED (post-sweep)
**Status: Resolved in code, but sweep data pre-dates the fix.** The engine previously used a default gossip fanout of 8 that always overrode chain-specific values due to a truthiness bug (`config.gossip_fanout or chain_config.gossip_fanout` evaluated to 8 because 8 is truthy). This has been corrected: the engine default is now 0, and the guard uses `if config.gossip_fanout` so that chain-specific fanout values (e.g., Solana's 200) take effect when configured.

**Important:** All sweep CSV data (including the λ=4,000 production sweep and sensitivity sweeps) was generated **before** this fix was applied, and therefore uses fanout-8 flat gossip for all chains. The fanout-8 model does not replicate Solana's Turbine tree-routing; it is a simplified flat gossip model. Regenerating the sweep with the corrected fanout logic would yield different propagation dynamics but has not been performed for this analysis.

### 1.4 Fixed Jitter Model
**Simplification:** The engine uses a fixed coefficient of variation (CV = 0.15) for latency jitter on all routes, regardless of geographic distance. A more physically motivated distance-dependent CV model exists in `simulator/models/latency.py` but is only exercised in tests, not by the main simulation.

### 1.5 P90 Coverage Caveat
**Simplification:** The P90 propagation metric is computed over whichever nodes have received the block within the simulation window. If only 60% of nodes receive a block (e.g., at very high PQC fractions), the P90 is the 90th percentile of that 60%, not the full network — potentially flattering the result in edge cases.

### 1.6 Off-by-One in Percentile Calculation — ✅ FIXED
~~**Known issue:** `propagation_percentile()` computes `index = int(N * p/100)`, which returns the `ceil` percentile rather than `floor`. For P90 with N=100, this gives the 91st element.~~

**Status: Fixed (commit `869265f`).** `propagation_percentile()` now uses the nearest-rank method: `index = max(0, ceil(N * p/100) - 1)`, which correctly returns the 90th element (index 89) for N=100, p=90. The bug history and rationale are documented inline in `simulator/network/propagation.py`.

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
| ML-DSA-44 | 54 | 180 | 3.3× |
| ML-DSA-65 | 87 | 300 | 3.4× |
| ML-DSA-87 | 140 | 500 | 3.6× |
| SLH-DSA-128f | ~1,500 | 5,940 | ~4.0× |
| Falcon-512 | ~30 | 100 | 3.3× |

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
At 0% PQC adoption, the simulator produces a mean stale rate of 0.0% with a P90 propagation delay of 186 ms (46.4% of the 400 ms slot). By comparison, Solana mainnet's observed slot skip rate during 2024–2025 is approximately 5%.

**Why the difference:** The simulator intentionally isolates the PQC signature-size channel by holding all other factors constant. The mainnet skip rate reflects additional real-world factors: validator software bugs, consensus voting overhead, leader rotation latency, clock drift, and transient network partitions — none of which relate to signature size or verification time.

### 4.2 Propagation Model Validation
The 186 ms P90 baseline is consistent with Decker and Wattenhofer's empirical propagation model (IEEE P2P, 2013) for ~563 KB blocks on a 75-node network with heterogeneous bandwidth.

---

## 5. Cross-Chain Extrapolation

### 5.1 Solana-Only DES Simulation
The Monte Carlo DES simulation (sweep CSV, sensitivity CSVs) was only run for a Solana-like chain. This is a deliberate design choice, not an omission.

**Rationale:** The DES engine targets **propagation latency** as the failure mode — the risk that PQC-inflated blocks cannot propagate within a chain's slot/block time, producing stale blocks. Solana's 400 ms slot is the only major chain where this failure mode is physically plausible: the measured P90 propagation at 100% PQC (~381 ms) consumes 95.3% of the slot budget. By contrast, the same 381 ms is only 3.2% of Ethereum's 12 s block time and 0.06% of Bitcoin's 10-minute block time — propagation is not a binding constraint.

Bitcoin and Ethereum face a **different failure mode**: capacity-bounded throughput collapse, where PQC signatures consume the block-weight budget (Bitcoin SegWit) or gas budget (Ethereum EVM) far faster than classical signatures. This is modelled exactly in the static Block-Space Analysis (Phase 1), which uses each chain's native cost model (SegWit weight units for Bitcoin, gas accounting for Ethereum). A DES simulation would add no additional insight for these chains because their block times provide orders-of-magnitude propagation headroom.

### 5.2 "Cross-Chain" Title
The project title "PQC Cross-Chain Simulator" reflects the full scope of the tool: the DES simulation (Solana propagation analysis), the static block-space analysis (exact per-chain capacity impact for all three chains), and the verification timing model. The "cross-chain" aspect is the comparative analysis across chains, not a claim that all three chains were DES-simulated.

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

### 3.14 `EthHybridRouting.fanout=16` — Understates Ethereum Peer Count

**Simplification:** Ethereum mainnet validators maintain ~100 peers on average. The simulator uses `fanout=16`, meaning only 16 peers are eligible to receive the block per hop. With `sqrt(16) = 4` direct-send peers and 12 announcement-only peers, far fewer nodes receive the block quickly than on mainnet. Combined with the 75-node scaled network, Ethereum propagation is modelled with much lower connectivity than reality. Absolute P90 values are likely conservative (higher than mainnet). Qualitative trends (PQC → slower propagation) are preserved.

### 3.15 `CompactBlockRouting.compact_fraction = 0.10` — Fixed Mempool Hit Rate

**Simplification:** Bitcoin BIP 152 compact blocks achieve ~10% of full block size when relay nodes have all transactions in their mempools (fast path). The `compact_fraction = 0.10` constant models this best case regardless of PQC adoption. In practice:
- At 0% PQC: relay nodes do have the classical transactions → 10% fraction is realistic.
- At 100% PQC: relay nodes have **never seen** PQC transactions → mempool hit rate ≈ 0% → relay must request the full block (compact_fraction → 1.0).

The fixed 0.10 value significantly understates Bitcoin relay latency at high PQC fractions. The model therefore underestimates Bitcoin propagation degradation under PQC load. This is a conservative assumption that makes PQC look less harmful than it is for Bitcoin relay hops.

---

## 9. Agent-Based Demand Model (Phase 4)

### 9.1 Agent Archetype Composition

**Assumption:** The agent pool uses chain-specific population mixes defined in `simulator/economics/user_agents.py` (`CHAIN_AGENT_MIX`). For the primary Solana simulation:

| Archetype | Fraction | Rationale |
|-----------|----------|-----------|
| `arb_bot` | 40% | Solana is dominated by high-frequency MEV/arbitrage activity |
| `defi_protocol` | 20% | Significant on-chain DeFi activity (Raydium, Orca, Jupiter) |
| `retail` | 30% | Retail SPL transfers and NFT mints |
| `whale` | 5% | Institutional validators and large-position holders |
| `exchange` | 5% | Centralised exchange withdrawal batches |

For Bitcoin, the mix is retail-dominant (60% retail, 25% exchange, 10% whale, 5% arb_bot), reflecting Bitcoin's payment/settlement use-case. For Ethereum, arb_bot and defi_protocol together account for 40%, consistent with on-chain MEV data (Flashbots, 2024).

**Justification:** These fractions are estimates, not empirically calibrated distributions. On-chain transaction type data is not directly observable from public mempool snapshots (intent is private until inclusion). The fractions are bounded by heuristic evidence: Flashbots reports 60–70% of Ethereum blocks contain MEV bundles; Chainalysis estimates retail transfers comprise 40–60% of Bitcoin transaction count. The model treats these as order-of-magnitude inputs, not precise measurements.

### 9.2 Agent Threshold Parameters

Each archetype has three key parameters: `max_fee_ratio` (fraction of tx value the agent tolerates as fee), `batch_threshold_ratio` (fee multiple above baseline that triggers batching), and `l2_migration_threshold_ratio` (fee multiple that triggers L2 migration). Default values:

| Archetype | max\_fee\_ratio | batch\_threshold | L2\_migration\_threshold | L2\_min\_blocks |
|-----------|----------------|-----------------|--------------------------|----------------|
| retail | 5% of tx value | 2× baseline | 5× baseline | 50 |
| whale | 1% of tx value | 20× (never) | 50× (never) | 1,000 |
| arb\_bot | 50% of profit | 100× (never) | 10× baseline | 2 |
| defi\_protocol | 2% of position | 3× baseline | 5× baseline | 100 |
| exchange | 0.1% of value | 1.5× baseline | 10× baseline | 500 |

**Simplification:** `will_submit()` uses a hard threshold comparison (`ratio <= batch_threshold_ratio × noise`) rather than a continuous probability function. The noise term (`gauss(0, 0.1)`) adds ±10% individual variation. A logistic demand curve (as used in the dual-sig migration model) would be more theoretically rigorous but introduces an additional shape parameter that is equally unconstrained by data.

**Impact:** The hard threshold model overstates the abruptness of demand destruction — in reality, submission probability declines gradually as fees approach and exceed agent thresholds. This makes the demand model a coarser approximation of real elasticity than the logistic formulation.

### 9.3 `blocks_elevated` Threshold (1.5×)

**Assumption:** The `blocks_elevated` counter increments when the current fee rate exceeds `1.5 × baseline_fee_rate`. This threshold is used to determine when L2 migration triggers (agents require `blocks_elevated ≥ l2_migration_min_blocks` sustained consecutive blocks at elevated fees before migrating).

**Justification:** The 1.5× multiplier is an ad-hoc choice representing a "materially elevated but not extreme" fee condition. No empirical evidence directly informs this value for PQC-inflated fees. Bitcoin and Ethereum historical mempool data show that retail users begin delaying transactions at approximately 1.5–3× median fee (Glassnode, 2022), which provides loose support for the lower bound.

**Impact:** A lower threshold (e.g., 1.2×) would trigger L2 migration sooner, amplifying demand destruction at moderate PQC fractions. A higher threshold (e.g., 2×) would suppress migration entirely for most simulation runs. The 1.5× value is intentionally conservative (makes PQC demand destruction look less severe).

### 9.4 `verification_cost_weight` and Censorship Incentive

**Assumption:** `BlockBuilder.verification_cost_weight = 0.0` by default (pure fee-per-resource ordering). When set to 0.3, the block priority score blends fee-per-resource (70%) with verification-efficiency fee-per-µs (30%), creating a rational censorship incentive: validators prefer Falcon-512 (100 µs verify) over SLH-DSA-128s (~1,000 µs verify) at equal absolute fees.

**Simplification:** The blending formula (`base_score × (1-w) + normalised_verify × w`) uses a fixed reference verification time of 60 µs (ECDSA baseline). This normalisation means the verify-efficiency component is interpretable relative to ECDSA but assumes validators have accurate per-transaction verify-time estimates before including them in a block — which is not true in practice (validators learn verify time only after performing verification).

**Impact:** The censorship incentive model is illustrative rather than mechanistically accurate. Real validator censorship would be driven by ex-post block reward shortfalls relative to slot time, not ex-ante verify-time predictions.

### 9.5 Agent Pool Size

**Default:** 500 agents per simulation run (configurable via `Phase2Config.agent_pool_size`). The default pool of 500 is a computational convenience, not an empirically motivated figure. Increasing to 5,000 agents would smooth the demand-reduction distribution but would add approximately 10× per-block agent simulation overhead.

**Statistical note:** At 500 agents with the Solana mix, the arb_bot cohort contains 200 agents and the retail cohort contains 150 agents — sufficient for smooth aggregate behaviour. Cohorts with 5% share (25 agents) may show higher variance in L2-migration counts during short simulations.

### 9.6 `tx_viability.py` — Analytical, Not Simulated

**Design choice:** `simulator/economics/tx_viability.py` is a pure analytical module — it does not run a discrete-event simulation. Fee estimates are computed from chain-specific formulae (sat/vbyte × tx_size for Bitcoin, gas × gwei + precompile for Ethereum, lamports/CU × CU\_COSTS for Solana) rather than sampled from the DES engine's fee market.

**Implication:** Viability thresholds (`MAX_FEE_FRACTION`) are static per-type constants, not drawn from an agent-preference distribution. The module answers "at a given fee rate, which transaction types are economically irrational?" rather than "what fraction of agents will stop submitting?" The two questions are complementary — the agent model answers the latter.

**`TYPICAL_TX_VALUES_USD` sourcing:** Dust threshold ($0.01 BTC) is derived from Bitcoin Core's `GetDustThreshold()` at a 3 sat/vbyte relay fee rate and a \$60,000 BTC price. Ethereum and Solana values are informed by Dune Analytics median transaction size distributions (2024) and should be treated as representative order-of-magnitude figures, not market-surveyed medians.

---

## 10. Solana Engineer Review Fixes (Post-Phase 4)

### 10.1 Falcon-512 CU Cost Ordering — ✅ FIXED (BUG-B)

**Previous inconsistency:** `CU_COSTS["Falcon-512"] = 2,500` and `CU_COSTS["ML-DSA-44"] = 5,000` in `solana_specific.py` implied Falcon-512 is twice as fast to verify on Solana as ML-DSA-44. This contradicts `blockchain/verification.py`, which correctly assigns Falcon-512 = 250 µs and ML-DSA-44 = 180 µs based on OQS Skylake benchmarks (Falcon-512 ~125 µs, ML-DSA-44 ~54 µs; simulator values include 2.5–3.3× conservative margins). Falcon's advantage is signature **size** (666 B vs 2,420 B), not verification speed.

**Fix:** `CU_COSTS["Falcon-512"]` updated to 6,500 CU and `CU_COSTS["Falcon-1024"]` to 11,000 CU, restoring the correct ordering: Falcon-512 > ML-DSA-44 in both wall-clock time and compute units. Hybrid scheme entries updated accordingly. The SLH-DSA entries are unaffected and remain correct.

**Impact on prior results:** The CU saturation analysis in `SolanaTxModel.block_capacity_analysis` is a standalone analytical path not used by the DES engine. DES simulation results are unaffected. The corrected CU ordering means Falcon-512 is now correctly identified as *more* CU-intensive than ML-DSA-44 for Solana vote verification — a non-obvious but physically correct result.

### 10.2 Agent Model Requires Fee Market — ✅ FIXED (BUG-C)

**Previous behaviour:** `Phase2Config(use_agent_demand_model=True, fee_market_enabled=False)` silently constructed an `AgentPool` but never consulted it. The agent modulation block was gated on `self._fee_market is not None`, so demand feedback was completely absent without a runtime error or warning.

**Fix:** `Phase2Engine.__init__` now raises `ValueError` immediately when `use_agent_demand_model=True` and `fee_market_enabled=False`. The error message explains why: the agent pool uses the current fee rate as its demand signal — without a fee market, there is no signal and the pool is useless.

### 10.3 Block Size Constant Alignment — ✅ FIXED (BUG-E)

**Previous inconsistency:** `solana_specific.py` used `BLOCK_SIZE_BYTES = 6,291,456` (6 MiB) while `base.py` and `chain_models.py` both used `6,000,000` (6 MB). The 4.7% difference caused `SolanaTxModel.block_capacity_analysis` to report slightly higher throughput figures than the DES engine.

**Fix:** `solana_specific.py BLOCK_SIZE_BYTES` set to `6_000_000` to match both other constants. All three Solana block-capacity analysis paths now use the same value.

### 10.4 TurbineRouting isinstance Check — ✅ FIXED (BUG-G)

**Previous code:** `self.routing.__class__.__name__ == "TurbineRouting"` in `engine.py`. String comparison fails silently for any subclass of `TurbineRouting`.

**Fix:** Replaced with `isinstance(getattr(self, "routing", None), TurbineRouting)`. `TurbineRouting` is now imported directly in `engine.py`.

### 10.5 Turbine Bounded-Gossip Approximation — DOCUMENTED (BUG-D)

**Limitation (not a bug in the simulation results):** The `TurbineRouting.plan_propagation` implementation is bounded-random gossip, not a deterministic shred tree. Real Turbine assigns each validator a fixed subtree via a PRNG seeded from the leader slot and shred index. The simulation's model — each sender selects `fanout` random recipients from all currently unseen nodes — is functionally correct for propagation coverage and hop count, but does not model the bandwidth concentration asymmetry between tree layers (layer-0 nodes bear 200× a leaf's load in a real tree).

**Impact:** Propagation latency and coverage metrics are unaffected for the 75-node test network (fanout=200 ≥ 74 → one hop). For a 1,500-node production simulation, the tree degenerates to two hops regardless of whether the assignment is random or deterministic. Bandwidth concentration is understated at layer-0 nodes and overstated at leaves.

A comment has been added to `TurbineRouting.plan_propagation` explicitly documenting this approximation.

### 10.6 Solana Validator Bandwidth Floor — ✅ FIXED (BUG-H)

**Previous issue:** The generic `VALIDATOR_TIERS["home"]` tier assigned 25–100 Mbps upload to 15% of validators. Solana's documented minimum hardware requirement is 300 Mbps upload ([Solana validator requirements](https://docs.solana.com/running-validator/validator-reqs)). Home-tier nodes below this threshold would be rejected from the network; modelling them inflates propagation delay estimates for the bottom quantile of Solana validators.

**Fix:** A `SOLANA_VALIDATOR_TIERS` dict has been added to `simulator/models/bandwidth.py` overriding the home tier with `upload_mbps = (300, 600)` (300–600 Mbps, matching high-speed residential fibre / business connections). `sample_validator_config()` now accepts a `chain` parameter and selects `SOLANA_VALIDATOR_TIERS` when `chain="solana"`. The DES engine passes `chain=self.config.chain` to all validator node creation calls.

**Impact:** Solana simulation runs will no longer create under-specced validator nodes. The practical effect on aggregate propagation metrics is small (only the bottom 15% of validators are affected, and they represent the home tier with disproportionately low stake weight), but it eliminates a known correctness issue.

### 10.7 Vote Transaction Model Inconsistency — DOCUMENTED (BUG-A + BUG-I)

**Three vote overhead models exist at different layers:**

1. `blockchain/chain_models.analyze_solana_block_space`: fraction-based deduction (`block_size × (1 - vote_tx_pct)`) with `vote_tx_pct=0.0` default.
2. `simulator/chains/solana_specific.SolanaTxModel.block_capacity_analysis`: individual-tx counting (`226 B × num_validators`).
3. `simulator/core/phase2_engine._inject_vote_transactions`: actual vote transactions injected into the mempool at each slot tick (simulation ground truth).

**Model 1 default overstates throughput:** With `vote_tx_pct=0.0`, `compare_all_solana()` ignores vote overhead entirely, overstating user-transaction throughput by ~3.3× relative to the realistic 70% vote scenario.

**Resolution:** `compare_all_solana()` now includes a docstring warning explaining this default and directing callers to pass `vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC (0.70)` for paper-facing analysis. A full unification of the three models (removing Models 1 and 2 in favour of Model 3) is deferred as it would require restructuring the static analysis API.

**Why 5.4% ≠ 75% mainnet:** The `SolanaTxModel` individual-tx model (`226 B × 1,500 validators = 339 KB = 5.4% of 6 MB`) appears to contradict the empirical 75% mainnet vote overhead. This is reconciled by noting that mainnet includes accumulated epoch-history vote account data in every block, not just the current slot's new attestations. The simulation correctly models only the current-slot vote transaction stream (226 B × N validators) — a deliberate simplification that is now explicitly documented here.

---

## 11. Multi-Chain Engineer Review Fixes

### 11.1 SegWit Marker+Flag Weight Classification — ✅ FIXED (BTC-1)

**Previous bug:** `BitcoinTxModel.base_size()` included the SegWit serialisation marker (`0x00`) and flag (`0x01`) in the header via `+2 for varint counts`, charging them at 4 WU/byte (non-witness weight). Per BIP 141, these 2 bytes are part of the extended witness serialisation and count at 1 WU/byte. The overcharge was `2 × 3 WU excess = 6 WU per transaction`.

**Fix:** Moved to `witness_size()` as `SEGWIT_MARKER_BYTES = 2`. `base_size()` now contains only version(4) + locktime(4) + varint counts(2) + inputs + outputs. For a 2-in-2-out ML-DSA-65 transaction (~5,261 WU in witness), the corrected base weight changes by ≈0.1% — tiny but technically correct per BIP 141.

### 11.2 Single Ethereum Calldata Gas Constant — ✅ FIXED (ETH-1)

**Previous issue:** `EthereumTxModel` (in `ethereum_specific.py`) and `analyze_ethereum_block_space` (in `chain_models.py`) each defined a separate `40` gas/byte literal for EIP-7623 calldata. Two separate literals are a maintenance hazard — any future update to one creates a silent divergence.

**Fix:** `ethereum_specific.py` now imports `ETHEREUM_CALLDATA_GAS_PER_BYTE` from `blockchain/chain_models.py` and uses it as the dataclass default. `chain_models.py` is the single source of truth. The deferred import inside `gas_overhead_ratio()` (ETH-5) was simultaneously moved to module top-level.

### 11.3 P2TR Quantum Exposure Weight — ✅ FIXED (BTC-3)

**Previous value:** `P2TR_DEFERRED_WEIGHT = 0.5`. The 0.5× discount reflected the assertion that P2TR's tweaked Schnorr key is "harder" to attack. This is incorrect — the Taproot tweak `Q = P + H(P,t)·G` does not add any quantum hardness. Shor's algorithm solves the discrete logarithm of `Q` in polynomial time regardless of the derivation path. The distinguishing property of P2TR is **spend velocity** (P2TR UTXOs are more actively managed and turn over faster), not quantum resilience.

**Fix:** `P2TR_DEFERRED_WEIGHT = 1.0`. Quantum exposure for P2TR is the same as P2WPKH. The faster spend velocity is already captured by `SPEND_FREQUENCY_FACTOR["P2TR"]`, which correctly models the higher turnover rate. This change increases the simulated deferred BTC exposure by the P2TR UTXO fraction (~15% of all UTXOs as of 2025).

**Sources:** BIP 341; Google Quantum AI — [Safeguarding cryptocurrency by disclosing quantum vulnerabilities responsibly](https://research.google/blog/safeguarding-cryptocurrency-by-disclosing-quantum-vulnerabilities-responsibly/).

### 11.4 Compact Block Efficiency vs PQC Adoption — ✅ FIXED (BTC-2)

**Previous issue:** `CompactBlockRouting` used a fixed `compact_fraction = 0.10` regardless of PQC adoption. This modelled relay nodes as always having 90% mempool overlap — a valid assumption for classical transactions but wrong for PQC transactions, which relay nodes have never seen before. At 100% PQC adoption, compact block relay degenerates to near full-block size, and the fixed 0.10 constant systematically underestimated Bitcoin relay latency where the paper's findings matter most.

**Fix:** `compact_fraction` is now a computed property: `base + (1 − base) × pqc_fraction` where base = 0.10. `get_routing_strategy()` accepts `pqc_adoption_fraction` and passes it through. DESEngine derives the fraction from the signature algorithm (0 for classical, 1.0 for PQC). Phase2Engine overrides with the exact `config.pqc_fraction` for mixed-algorithm blocks.

**Impact:** At 100% PQC, Bitcoin relay nodes now send the full block (compact_fraction = 1.0), increasing simulated Bitcoin propagation latency at high PQC fractions.

### 11.5 CRQC Probability Distribution — DOCUMENTED (BTC-4)

**Acknowledged inconsistency:** `QuantumExposureModel.exposure_timeline()` uses a logistic CDF (symmetric) despite the attribute being named `crqc_sigma_years` and the docstring referencing "log-normal uncertainty." Security literature (Mosca 2022) favours log-normal or Weibull distributions for CRQC arrival timing because the right tail (later-than-expected CRQC) carries more probability mass than the left tail.

**Resolution:** A clarifying comment has been added at the implementation site. The logistic CDF is a defensible approximation for central estimates and sensitivity analyses but underestimates the probability of a late-but-sudden CRQC arrival. The docstring attribute name is intentionally left as `crqc_sigma_years` for backwards compatibility; the comment explains the mismatch.

**Source:** Google Quantum AI — [Safeguarding cryptocurrency by disclosing quantum vulnerabilities responsibly](https://research.google/blog/safeguarding-cryptocurrency-by-disclosing-quantum-vulnerabilities-responsibly/).

### 11.6 Ethereum Announcement Size — ✅ FIXED (ETH-4)

**Previous value:** `EthHybridRouting.ANNOUNCEMENT_SIZE_BYTES = 100`. The devp2p `NewBlockHashes` message (eth/68 wire protocol) contains `[hash(32), number(8)]` per entry plus ~8 bytes RLP framing = 48 bytes. The 100-byte estimate was approximately 2× the actual size.

**Fix:** `ANNOUNCEMENT_SIZE_BYTES = 48`. Impact on latency is negligible (announcements are tiny relative to full blocks) but the constant is now protocol-accurate.

**Source:** [Ethereum devp2p eth/68 wire protocol spec](https://github.com/ethereum/devp2p/blob/master/caps/eth.md#newblockhashes-0x01).

### 11.7 Solana `compare_all_solana()` Default Vote Fraction — ✅ FIXED (SOL-4)

**Previous default:** `vote_tx_pct=0.0` overstated Solana user-transaction throughput by ~3.3×.

**Fix:** Default changed to `vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC = 0.70`. Callers needing the old zero-overhead behaviour must now pass `vote_tx_pct=0.0` explicitly.

### 11.8 SLH-DSA f/s Naming — DOCUMENTED (VER-1)

Inline comments added to every SLH-DSA entry in `VERIFICATION_PROFILES`. The counter-intuitive FIPS 205 naming convention ("f" = fast signing, slow verification; "s" = slow signing, fast verification) is now flagged directly at each entry, not only in the file header. `SLH-DSA-128f` verifies 2.75× slower than `SLH-DSA-128s`.

### 11.9 Falcon Batch Verification Speedup — ✅ FIXED (VER-2)

**Previous value:** `Falcon-512 batch_speedup = 1.0` (no batch speedup). Falcon verification uses an NTT over a polynomial ring; shared NTT butterfly computations across multiple signatures yield an empirical 30–40% per-signature speedup in batch mode.

**Fix:** `Falcon-512 batch_speedup = 0.65` (35% speedup; conservative vs Ed25519 Bos-Coster 50%). `Falcon-1024` updated identically. For validators processing many Falcon signatures per slot, this reduces the verification bottleneck estimate. The impact is modest because batch verification is only invoked when `use_batch=True` in `compute_block_verification_time()`.

**Source:** Falcon NIST round-3 submission, Section 3.11.1; OQS team NTT pipelining notes.

### 11.10 Dead Code and Variable Shadow — ✅ FIXED (ENG-1, ENG-2)

**ENG-1:** `DESEngine._select_gossip_peers()` removed. The method was explicitly labelled `[DEPRECATED — dead code]` and was never called in any code path. The "downstream forks" justification for retaining it does not apply to an academic codebase.

**ENG-2:** Duplicate `total_blocks = len(self.state.blocks_proposed)` assignment in `_compute_results()` removed. The second assignment was identical to the first and served no purpose.
