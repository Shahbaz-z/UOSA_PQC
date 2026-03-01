# Implementation Plan: PQC Cross-Chain Simulator

## Vision

Transform the project from a static block-space educator into a **cross-chain simulator quantifying how PQC signatures change security, decentralisation, and fees in real blockchain networks**.

Architecture pipeline:
```
Crypto Benchmarks (have) -> Transaction Model -> Network Simulator -> Incentive Engine -> Risk Metrics
```

---

## PHASE 1: Clean-up and Foundation (Immediate)

### 1.1 Remove QR Score Section Entirely

**Rationale:** The QR score combines qualitative hardcoded numbers (migration feasibility, ZK readiness) with quantitative analysis. It produces misleading composite scores (e.g., "Ethereum: C, 65.9") that look precise but are partly subjective. The new simulator will replace this with measurable risk metrics.

**Files to delete:**
- `blockchain/qr_score.py` (365 lines)
- `app/tabs/qr_score.py` (167 lines)
- `tests/test_qr_score.py` (430 lines)

**Files to modify:**
- `app/tabs/__init__.py` -- remove `render_qr_score` import/export
- `app/pqc_demo_streamlit.py` -- remove QR Score tab, update tab list from 5 to 4 (then 3 after ZK removal)
- `app/components/charts.py` -- remove `qr_radar_chart()` and `qr_composite_bar_chart()` functions, remove any QR-related imports
- `docs/methodology.md` -- remove Section 4 (QR Scoring Model)
- `README.md` -- remove QR Score references

**Tests to update:**
- Remove all tests that import from `blockchain.qr_score`

### 1.2 Reassess ZK-STARKs & Remove ZK-SNARKs

**Assessment of current ZK code:** The ZK tab displays hardcoded proof sizes from literature and performs simple gas arithmetic. It does NOT generate real proofs, verify constraints, or simulate FRI protocols. The ZK-SNARK systems (Groth16, PLONK, Halo2) are not quantum-resistant and are irrelevant to a PQC-focused simulator.

**Decision: Remove ZK-SNARKs entirely. Retain ZK-STARKs only if repurposed.**

The ZK-STARK data (STARK-S: 45KB proof, 1.2M gas; STARK-L: 200KB proof, 5M gas) is factually accurate and relevant to quantum resistance. However, as a standalone tab it's superficial -- it just shows "STARKs are quantum-resistant, SNARKs aren't" with some gas math.

**Action: Remove the entire ZK tab and ZK models for now.** The STARK proof size/gas data will be reintegrated later (Phase 3) into the network simulator as a transaction type -- i.e., "what happens to the network when ZK-STARK rollup settlement transactions compete for block space alongside PQC signature transactions?" This is more useful than a standalone comparison page.

**Files to delete:**
- `blockchain/zk_models.py` (391 lines)
- `app/tabs/zk_proofs.py` (230 lines)
- `tests/test_zk_models.py` (383 lines)

**Files to modify:**
- `app/tabs/__init__.py` -- remove `render_zk_proofs` import/export
- `app/pqc_demo_streamlit.py` -- remove ZK tab from tab list, remove import
- `app/components/charts.py` -- remove 4 ZK chart functions (`zk_proof_size_vs_gas_chart`, `zk_throughput_comparison_chart`, `zk_gas_breakdown_chart`, `zk_vs_signatures_chart`), remove `ZKProofAnalysis` import
- `docs/methodology.md` -- remove Section 3 (ZK Proof System Models)

### 1.3 Add Verification Time Modeling

**Problem:** Current models count how many transactions *fit* in a block but ignore how long it takes to *verify* them. PQC verification is significantly slower than classical crypto. A block might fit 1,000 Falcon-512 transactions but take 3 seconds to verify, exceeding Solana's 400ms slot time.

**Implementation:**

Create `blockchain/verification.py`:

```python
@dataclass
class VerificationProfile:
    algorithm: str
    verify_time_us: float       # Microseconds per single verification
    batch_speedup: float        # Multiplier for batch verification (1.0 = no speedup)
    parallelizable: bool        # Can be parallelized across cores

# Calibrated from liboqs benchmarks and published literature
VERIFICATION_TIMES: Dict[str, VerificationProfile] = {
    "Ed25519":      VerificationProfile("Ed25519",      60,   0.5, True),   # ~60μs, batch-friendly
    "ECDSA":        VerificationProfile("ECDSA",         80,   1.0, True),   # ~80μs
    "Schnorr":      VerificationProfile("Schnorr",       60,   0.4, True),   # batch-friendly (MuSig)
    "ML-DSA-44":    VerificationProfile("ML-DSA-44",    250,   1.0, True),   # ~250μs
    "ML-DSA-65":    VerificationProfile("ML-DSA-65",    400,   1.0, True),   # ~400μs
    "ML-DSA-87":    VerificationProfile("ML-DSA-87",    600,   1.0, True),   # ~600μs
    "Falcon-512":   VerificationProfile("Falcon-512",   120,   1.0, True),   # ~120μs (fast verify)
    "Falcon-1024":  VerificationProfile("Falcon-1024",  250,   1.0, True),   # ~250μs
    "SLH-DSA-128s": VerificationProfile("SLH-DSA-128s", 3000,  1.0, True),  # ~3ms (slow!)
    "SLH-DSA-128f": VerificationProfile("SLH-DSA-128f", 500,   1.0, True),  # fast variant
    "SLH-DSA-256f": VerificationProfile("SLH-DSA-256f", 2000,  1.0, True),
    ...hybrids (sum of both)...
}
```

Add `compute_block_verification_time()`:
```python
def compute_block_verification_time(
    algorithm: str,
    txs_per_block: int,
    num_cores: int = 4,
) -> VerificationResult:
    """How long to verify all signatures in a block."""
    profile = VERIFICATION_TIMES[algorithm]
    serial_time_ms = (profile.verify_time_us * txs_per_block) / 1000
    parallel_time_ms = serial_time_ms / num_cores if profile.parallelizable else serial_time_ms
    return VerificationResult(
        total_serial_ms=serial_time_ms,
        total_parallel_ms=parallel_time_ms,
        exceeds_block_time=parallel_time_ms > block_time_ms,
        verification_bottleneck_ratio=parallel_time_ms / block_time_ms,
    )
```

**Integration into chain models:** Each `BlockAnalysis` result gets a new field `verification_time_ms` and `verification_limited_tps` that caps throughput at the verification bottleneck:
```
effective_tps = min(block_space_tps, verification_limited_tps)
```

**New field on BlockAnalysis:**
- `verification_time_ms: float` -- time to verify all sigs in a block
- `effective_tps: float` -- min(space-limited, verification-limited)
- `bottleneck: str` -- "block_space" or "verification"

### 1.4 Add Signature Aggregation Models

**Problem:** The model assumes 1 signature per signer per transaction. In practice, aggregation schemes can combine multiple signatures into one, dramatically reducing overhead.

Create `blockchain/aggregation.py`:

```python
@dataclass
class AggregationScheme:
    name: str
    aggregated_sig_size: Callable[[int], int]   # f(num_sigs) -> total bytes
    aggregated_pk_size: Callable[[int], int]
    verification_time_factor: float             # multiplier vs single-sig verify
    supported_algorithms: List[str]
    quantum_resistant: bool

AGGREGATION_SCHEMES = {
    "None": AggregationScheme(
        name="No Aggregation",
        aggregated_sig_size=lambda n, algo: SIGNATURE_SIZES[algo] * n,
        aggregated_pk_size=lambda n, algo: PUBLIC_KEY_SIZES[algo] * n,
        verification_time_factor=1.0,
        supported_algorithms=list(SIGNATURE_SIZES.keys()),
        quantum_resistant=None,  # depends on underlying algo
    ),
    "BLS": AggregationScheme(
        name="BLS Aggregation",
        aggregated_sig_size=lambda n, algo: 48,       # Constant 48 bytes regardless of n
        aggregated_pk_size=lambda n, algo: 48 * n,    # PKs don't aggregate easily
        verification_time_factor=1.5,                  # Pairing check is slower
        supported_algorithms=["BLS12-381"],
        quantum_resistant=False,                        # Pairing-based, Shor breaks it
    ),
    "Falcon-Tree": AggregationScheme(
        name="Falcon Merkle Tree Aggregation",
        aggregated_sig_size=lambda n, algo: 666 + 32 * math.ceil(math.log2(max(n, 1))),
        aggregated_pk_size=lambda n, algo: 32,         # Merkle root only
        verification_time_factor=1.2,
        supported_algorithms=["Falcon-512", "Falcon-1024"],
        quantum_resistant=True,
    ),
    "ML-DSA-Batch": AggregationScheme(
        name="ML-DSA Batch Verification",
        aggregated_sig_size=lambda n, algo: SIGNATURE_SIZES.get(algo, 3293) * n,  # No size reduction
        aggregated_pk_size=lambda n, algo: PUBLIC_KEY_SIZES.get(algo, 1952) * n,
        verification_time_factor=0.6,                  # ~40% faster verification in batch
        supported_algorithms=["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"],
        quantum_resistant=True,
    ),
}
```

**Integration:** Add an `aggregation_scheme` parameter to each `analyze_*_block_space()` function. When set, the effective signature size per transaction changes based on the aggregation function.

### 1.5 Streamlit UI Integration Tests

**Problem:** Only chart functions and model logic are unit-tested. The Streamlit tabs are untested -- a broken import or missing column would only be caught by manual testing.

Create `tests/test_ui_integration.py`:

Use `streamlit.testing.v1.AppTest` (available since Streamlit 1.28):

```python
from streamlit.testing.v1 import AppTest

class TestBlockSpaceTab:
    def test_app_loads_without_error(self):
        at = AppTest.from_file("app/pqc_demo_streamlit.py")
        at.run(timeout=30)
        assert not at.exception, f"App raised: {at.exception}"

    def test_tabs_render(self):
        at = AppTest.from_file("app/pqc_demo_streamlit.py")
        at.run(timeout=30)
        # Verify tab headers exist
        assert len(at.tabs) >= 3

    def test_solana_analysis_produces_table(self):
        # Test that block-space tab renders a data table
        at = AppTest.from_file("app/pqc_demo_streamlit.py")
        at.run(timeout=30)
        # Check that dataframes are generated
        assert len(at.dataframe) > 0 or len(at.table) > 0
```

Test categories:
1. **Smoke tests:** App loads without exception
2. **Tab rendering:** Each tab produces expected widget types
3. **Data consistency:** Tables contain expected columns
4. **Sidebar content:** Educational content renders

---

## PHASE 2: Project Identity Overhaul

### 2.1 Rename & Rebrand

**Old:** "Blockchain Quantum Resistance Educator"
**New:** "PQC Chain Simulator: Cross-Chain Impact of Post-Quantum Signatures on Security, Decentralisation & Fees"

Update:
- `app/pqc_demo_streamlit.py` -- title, description, sidebar
- `README.md` -- full rewrite
- `docs/methodology.md` -- restructure around simulation pipeline

### 2.2 Restructure Tabs

**Old tabs:** Block-Space | Comparison | Cross-Chain | (ZK removed) | (QR removed)
**New tabs:**
1. **Crypto Benchmarks** -- Keep existing comparison tab (keygen/sign/verify real measurements)
2. **Block-Space Impact** -- Keep existing block-space tab (refactored with verification time + aggregation)
3. **Network Simulator** -- NEW (Phase 3)
4. **Fee Market** -- NEW (Phase 3)
5. **Risk Dashboard** -- NEW (Phase 3)

### 2.3 Refactor Transaction Model

Extend `blockchain/chain_models.py` to produce a `Transaction` object that flows through the entire pipeline:

```python
@dataclass
class Transaction:
    chain: str
    sig_algorithm: str
    tx_type: str                    # "transfer", "token_transfer", "dex_swap", "zk_proof"
    size_bytes: int                 # total serialized size
    weight_units: int               # Bitcoin: WU, others: same as bytes
    gas_cost: int                   # Ethereum: gas, others: 0
    verification_time_us: float     # microseconds to verify this tx
    fee_bid: float                  # native currency units the user is willing to pay
    priority: float                 # derived from fee_bid / size
```

This transaction object is the input to the network simulator and fee market.

---

## PHASE 3: Network Simulator (Major Addition)

### 3.1 Geographic Latency Matrix

Create `simulator/network.py`:

Model validator nodes distributed across geographic regions with realistic latency:

```python
REGIONS = ["US-East", "US-West", "EU-West", "EU-East", "Asia-East", "Asia-SE", "South-America"]

# One-way latency in milliseconds (measured from AWS inter-region latency data)
LATENCY_MATRIX = {
    ("US-East", "US-West"): 62,
    ("US-East", "EU-West"): 85,
    ("US-East", "Asia-East"): 180,
    ...
}
```

### 3.2 Heterogeneous Validator Bandwidth

Not all validators have the same bandwidth. Model a distribution:

```python
@dataclass
class ValidatorNode:
    region: str
    bandwidth_mbps: float           # Upload bandwidth
    cpu_cores: int                  # For parallel verification
    memory_gb: float
    is_staking: bool                # Solana: validator, Bitcoin: miner, Ethereum: validator

# Distribution: 20% home stakers (25 Mbps), 50% cloud (1 Gbps), 30% datacenter (10 Gbps)
VALIDATOR_BANDWIDTH_DISTRIBUTION = {
    "home":       {"fraction": 0.20, "bandwidth_mbps": 25,   "cores": 4},
    "cloud":      {"fraction": 0.50, "bandwidth_mbps": 1000, "cores": 8},
    "datacenter": {"fraction": 0.30, "bandwidth_mbps": 10000,"cores": 32},
}
```

### 3.3 Block Propagation Model

```python
def compute_block_propagation(
    block_size_bytes: int,
    validator_set: List[ValidatorNode],
    latency_matrix: Dict,
) -> PropagationResult:
    """
    Model: time for a block to reach X% of validators.

    propagation_time_to_node = latency + (block_size / bandwidth)

    Returns distribution: time to reach 50%, 90%, 95%, 99% of validators.
    """
```

### 3.4 Stale/Orphan Block Rate

```python
def compute_stale_rate(
    block_time_ms: float,
    propagation_p95_ms: float,
) -> float:
    """
    Simplified model: P(stale) ≈ propagation_delay / block_time

    More accurate: P(stale) = 1 - e^(-propagation_delay / block_time)
    (Poisson process for competing blocks)

    With PQC: larger blocks -> slower propagation -> higher stale rate
    """
```

### 3.5 Minimum Viable Node Hardware

Compute the minimum hardware needed to keep up with the chain:

```python
def minimum_viable_node(
    chain: str,
    algorithm: str,
    target_sync_ratio: float = 1.0,  # Must process blocks as fast as they arrive
) -> HardwareRequirements:
    """
    bandwidth_required = block_size / block_time
    cpu_required = verify_time_per_block / block_time * safety_margin
    storage_growth = block_size * blocks_per_day
    """
```

This directly measures **decentralisation impact** -- if PQC raises minimum hardware requirements, fewer nodes can participate.

### 3.6 Mempool & Block Relay

```python
@dataclass
class Mempool:
    """Pending transaction pool with arrival process."""
    transactions: List[Transaction]
    arrival_rate_tps: float         # Poisson arrival rate
    max_size_bytes: int

def simulate_mempool_arrival(
    duration_seconds: float,
    tx_mix: Dict[str, float],       # {"transfer": 0.6, "token": 0.2, "dex": 0.15, "zk_proof": 0.05}
    arrival_rate: float,
    sig_algorithm: str,
) -> List[Transaction]:
    """Generate a realistic stream of transactions over time."""
```

### 3.7 Chain-Specific Architecture Respect

Each chain gets its own simulator subclass that respects architectural differences:

**Solana:**
- 400ms slots, continuous block production
- Gulf Stream: forward transactions to next leader
- Vote transactions consume 70-80% of block space
- Parallel execution (Sealevel) -- verification can be parallelized across accounts
- Turbine: block data shredding for propagation

**Bitcoin:**
- 10-minute blocks, Poisson arrival
- Compact block relay (BIP 152) -- only send short IDs, not full blocks
- UTXO model: signature exposure risk differs by address type
- Difficulty adjustment every 2016 blocks
- SegWit witness discount for propagation calculation

**Ethereum:**
- 12-second slots, deterministic block production
- Proposer-builder separation (PBS) -- builders optimize block content
- EIP-1559 base fee mechanism
- Blob transactions (EIP-4844) for rollup data
- Account abstraction (EIP-4337) -- wallets can use different sig schemes

---

## PHASE 4: Incentive Engine (Economic Behavior)

### 4.1 Adaptive Fee Market

Create `simulator/fee_market.py`:

```python
@dataclass
class FeeMarketState:
    base_fee: float                 # EIP-1559 style base fee (all chains)
    congestion_level: float         # 0-1 (how full are recent blocks)
    price_per_byte: float           # Effective cost per byte of transaction data
    price_per_gas: float            # Ethereum-specific

def adaptive_fee_market(
    chain: str,
    mempool: Mempool,
    recent_blocks: List[Block],
    sig_algorithm: str,
) -> FeeMarketState:
    """
    When PQC makes transactions larger:
    1. Blocks fill faster -> congestion rises -> base fee increases
    2. Fee per tx rises -> some users can't afford transactions
    3. Users batch transactions to amortise signature overhead
    4. Whales outbid small users for scarce block space
    5. Validators/builders prioritise cheap-to-verify transactions
    6. Some transaction types become uneconomical and disappear
    """
```

### 4.2 User Behavioral Response

```python
@dataclass
class UserBehavior:
    """How users adapt to changed fee conditions."""
    batch_probability: float        # Probability of batching multiple ops in one tx
    abandon_threshold: float        # Fee level at which user abandons tx
    willingness_to_pay: float       # Distribution parameter

def model_user_response(
    classical_fee: float,
    pqc_fee: float,
    user_type: str,                 # "retail", "whale", "bot", "defi_protocol"
) -> UserBehavior:
    """
    Fee elasticity: when fees 2x, retail users batch; when 5x, they leave.
    Whales absorb higher fees. Bots optimise for smallest signatures.
    DeFi protocols may switch to L2s or adopt aggregation.
    """
```

### 4.3 Validator/Builder Behavior

```python
def model_validator_strategy(
    mempool: Mempool,
    fee_market: FeeMarketState,
) -> BlockTemplate:
    """
    Validators maximise revenue: select transactions by fee/resource ratio.

    With PQC:
    - Large-sig txs offer less fee/byte -> deprioritised
    - Validators prefer Falcon-512 (small) over ML-DSA-87 (large)
    - Creates signature scheme selection pressure
    - Censorship incentive: exclude expensive-to-verify PQC schemes
    """
```

### 4.4 Transaction Type Viability

```python
def compute_tx_type_viability(
    chain: str,
    algorithm: str,
    fee_market: FeeMarketState,
) -> Dict[str, TxTypeViability]:
    """
    Some tx types become uneconomical with PQC:
    - Dust transactions (< $1 value) may cost more in fees than they transfer
    - Complex DeFi (multiple signatures) becomes very expensive
    - NFT mints with metadata may exceed block limits

    Returns viability assessment per transaction type.
    """
```

---

## PHASE 5: Risk Metrics Dashboard

### 5.1 System-Level Metrics

Create `simulator/risk_metrics.py`:

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| Block propagation delay (p50/p95) | Network sim output | How fast blocks reach validators |
| Stale/orphan block rate | P(stale) = 1 - e^(-t_prop/t_block) | Wasted work, reduced effective throughput |
| Fork probability | f(stale_rate, validator_distribution) | Chain safety/finality risk |
| Validator bandwidth saturation | block_size/block_time vs bandwidth | Decentralisation pressure |
| Minimum viable node hardware | CPU + bandwidth + storage requirements | Decentralisation floor |
| Fee equilibrium shift | New steady-state fee vs classical | Economic impact on users |
| Censorship incentive | fee_diff(cheap_algo, expensive_algo) | Centralisation/censorship risk |
| Effective throughput | min(space_limited, verify_limited, propagation_limited) | Real-world TPS accounting for all bottlenecks |
| Nakamoto coefficient change | f(hardware_requirements) | How many entities needed to control 51% |

### 5.2 Calibration Against Real Chain Data

Before adding PQC, the simulator must match current reality:

**Calibration targets (from public chain data):**

| Metric | Solana | Bitcoin | Ethereum |
|--------|--------|---------|----------|
| Actual avg TPS | ~700-1500 | ~3-7 | ~12-15 |
| Block utilisation | ~30-50% | ~50-80% | ~50-90% |
| Stale/orphan rate | ~5-8% slot skip | <1% | ~1-2% missed slots |
| Median fee | ~0.00025 SOL | ~10-50 sat/vB | ~5-30 gwei |
| Block propagation p95 | ~1-2s | ~5-15s | ~2-4s |
| Min node bandwidth | ~100 Mbps | ~10 Mbps | ~25 Mbps |

**Implementation:** Add `simulator/calibration.py` that:
1. Defines calibration targets from published chain data
2. Runs the simulator with classical signatures
3. Compares output metrics to calibration targets
4. Reports calibration error and adjusts parameters
5. Only after calibration passes, run PQC scenarios

### 5.3 Sensitivity Analysis

Create `simulator/sensitivity.py`:

```python
def sensitivity_analysis(
    chain: str,
    base_algorithm: str,
    parameter: str,                 # Which parameter to sweep
    range_values: List[float],
    metrics: List[str],             # Which metrics to track
) -> SensitivityResult:
    """
    Sweep one parameter while holding others constant.
    Plot metric response curves to identify:
    - Tipping points (where stale rate spikes)
    - Diminishing returns (where aggregation stops helping)
    - Counterintuitive results (where larger sigs help because they reduce congestion)
    """
```

**Key sensitivity sweeps:**
1. Signature size vs stale rate (expect nonlinear spike)
2. Verification time vs effective TPS (expect cliff)
3. Validator bandwidth vs Nakamoto coefficient (decentralisation pressure)
4. Fee elasticity vs transaction volume (demand destruction)
5. Aggregation batch size vs throughput recovery

### 5.4 Counterintuitive Results to Look For

The simulator should surface results that defy naive expectation:
- **Larger signatures might improve security economics** -- if they push out spam and dust transactions, average transaction quality improves
- **Falcon-512 isn't always best** -- if verification is the bottleneck (not size), ML-DSA's similar verify time but stronger security margin might win
- **Bitcoin may handle PQC better than Solana** -- 10-minute blocks absorb propagation delays; SegWit discount helps; low TPS means verification isn't a bottleneck
- **Ethereum gas limit increases may backfire** -- 180M gas allows more PQC txs but also increases block propagation time
- **Fee markets create natural PQC adoption pressure** -- validators preferring small-sig txs creates economic incentive to adopt Falcon over ML-DSA

---

## PHASE 6: Documentation & Testing

### 6.1 Methodology Rewrite

Rewrite `docs/methodology.md` to cover:
1. Crypto benchmarks (existing, updated)
2. Transaction model (extended with verification + aggregation)
3. Network simulation model (latency, propagation, stale rates)
4. Fee market model (adaptive pricing, user behavior)
5. Risk metrics (calibration, sensitivity)
6. Calibration methodology and data sources
7. Limitations and assumptions

### 6.2 Test Suite Expansion

Target: comprehensive coverage of all new modules:

| Module | Test File | Key Tests |
|--------|-----------|-----------|
| `blockchain/verification.py` | `tests/test_verification.py` | Verification times, bottleneck detection, parallel speedup |
| `blockchain/aggregation.py` | `tests/test_aggregation.py` | Aggregation size reduction, scheme compatibility |
| `simulator/network.py` | `tests/test_network.py` | Latency matrix, propagation times, stale rates |
| `simulator/fee_market.py` | `tests/test_fee_market.py` | Fee equilibrium, user response, validator strategy |
| `simulator/risk_metrics.py` | `tests/test_risk_metrics.py` | Metric computation, calibration targets |
| `simulator/calibration.py` | `tests/test_calibration.py` | Classical baseline matches real data |
| `simulator/sensitivity.py` | `tests/test_sensitivity.py` | Parameter sweeps, result structure |
| `tests/test_ui_integration.py` | - | App loads, tabs render, no exceptions |

---

## Implementation Order

### Sprint 1 (Phase 1): Clean-up
1. Remove QR score (all files, tests, references)
2. Remove ZK-SNARKs and ZK-STARKs tab (all files, tests, references)
3. Add `blockchain/verification.py` with verification time modeling
4. Integrate verification times into `BlockAnalysis` and chain models
5. Add `blockchain/aggregation.py` with aggregation schemes
6. Integrate aggregation into chain model functions
7. Add `tests/test_ui_integration.py` with Streamlit AppTest
8. Update existing tests for removed/changed modules
9. Verify all tests pass

### Sprint 2 (Phase 2): Identity & Transaction Model
10. Rename/rebrand project
11. Restructure tabs (3 existing + placeholders for new)
12. Create `Transaction` dataclass as pipeline object
13. Refactor chain models to produce `Transaction` objects
14. Update methodology docs

### Sprint 3 (Phase 3): Network Simulator
15. Create `simulator/` package
16. Implement geographic latency matrix
17. Implement validator bandwidth distribution
18. Implement block propagation model
19. Implement stale/orphan rate calculation
20. Implement minimum viable node computation
21. Implement mempool arrival process
22. Chain-specific simulator subclasses (Solana, Bitcoin, Ethereum)
23. Network Simulator tab in UI
24. Tests for all simulator components

### Sprint 4 (Phase 4): Incentive Engine
25. Implement adaptive fee market
26. Implement user behavioral response model
27. Implement validator/builder strategy
28. Implement transaction type viability analysis
29. Fee Market tab in UI
30. Tests for all incentive components

### Sprint 5 (Phase 5): Risk Dashboard & Calibration
31. Implement risk metrics computation
32. Implement calibration against real chain data
33. Implement sensitivity analysis engine
34. Risk Dashboard tab in UI
35. Document counterintuitive findings
36. Full test suite expansion
37. Methodology doc rewrite
38. README rewrite
