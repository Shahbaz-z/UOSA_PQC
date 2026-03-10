"""Bitcoin PQC impact analysis — block weight, fee market, witness policies.

Analytical (not simulation-based) models that answer:
1. How many fewer transactions fit per block with PQC signatures?
2. How do different SegWit witness discount policies affect capacity?
3. What are the fee market dynamics when PQC txs compete with ECDSA?

All computations are deterministic and fast (< 5 s for full analysis).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    ECDSA,
    PQC_ALGORITHMS,
    PQCAlgorithm,
)


# ── Constants ───────────────────────────────────────────────────────
BLOCK_WEIGHT_LIMIT = 4_000_000   # Weight units
BLOCK_INTERVAL_S = 600           # 10 minutes
MAINNET_ECDSA_TXS_PER_BLOCK = 2_800  # Approximate real-world average


# ── Witness discount policies ──────────────────────────────────────
@dataclass(frozen=True)
class WitnessPolicy:
    """Defines how witness (signature) bytes count toward block weight.

    Under standard SegWit (BIP-141):
        weight = non_witness_bytes * 4 + witness_bytes * 1

    We parameterise the witness multiplier to explore policy alternatives.
    """

    name: str
    witness_multiplier: float   # weight-units per witness byte
    base_multiplier: float = 4.0  # weight-units per non-witness byte


CURRENT_SEGWIT = WitnessPolicy("Current SegWit (1x witness)", witness_multiplier=1.0)
EXTENDED_DISCOUNT = WitnessPolicy("Extended discount (0.5x witness)", witness_multiplier=0.5)
NO_DISCOUNT = WitnessPolicy("No discount (4x all)", witness_multiplier=4.0)

ALL_POLICIES = [CURRENT_SEGWIT, EXTENDED_DISCOUNT, NO_DISCOUNT]


# ── Bitcoin Tx sizing (mirrors simulator/chains/bitcoin_specific.py) ─
@dataclass
class BitcoinTxSizer:
    """Compute tx weight under arbitrary witness policies."""

    avg_inputs: int = 2
    avg_outputs: int = 2

    # Fixed component sizes (bytes)
    VERSION_BYTES: int = 4
    LOCKTIME_BYTES: int = 4
    INPUT_PREVOUT_BYTES: int = 36
    INPUT_SEQUENCE_BYTES: int = 4
    INPUT_SCRIPTLEN_BYTES: int = 1
    OUTPUT_VALUE_BYTES: int = 8
    OUTPUT_SCRIPT_BYTES: int = 26
    WITNESS_ITEM_OVERHEAD: int = 2

    def base_bytes(self) -> int:
        """Non-witness transaction bytes."""
        header = self.VERSION_BYTES + self.LOCKTIME_BYTES + 2  # varint counts
        inputs = self.avg_inputs * (
            self.INPUT_PREVOUT_BYTES + self.INPUT_SEQUENCE_BYTES + self.INPUT_SCRIPTLEN_BYTES
        )
        outputs = self.avg_outputs * (self.OUTPUT_VALUE_BYTES + self.OUTPUT_SCRIPT_BYTES)
        return header + inputs + outputs

    def witness_bytes(self, sig_bytes: int, pk_bytes: int) -> int:
        """Witness data bytes."""
        per_input = sig_bytes + pk_bytes + self.WITNESS_ITEM_OVERHEAD
        return self.avg_inputs * per_input

    def tx_weight(self, sig_bytes: int, pk_bytes: int, policy: WitnessPolicy = CURRENT_SEGWIT) -> float:
        """Weight units under a given witness policy."""
        base = self.base_bytes()
        witness = self.witness_bytes(sig_bytes, pk_bytes)
        return base * policy.base_multiplier + witness * policy.witness_multiplier

    def txs_per_block(
        self,
        sig_bytes: int,
        pk_bytes: int,
        policy: WitnessPolicy = CURRENT_SEGWIT,
        block_weight_limit: int = BLOCK_WEIGHT_LIMIT,
    ) -> int:
        w = self.tx_weight(sig_bytes, pk_bytes, policy)
        return int(block_weight_limit // w) if w > 0 else 0

    def tx_vsize(self, sig_bytes: int, pk_bytes: int) -> float:
        """Virtual size = weight / 4 (for fee-rate computation)."""
        return self.tx_weight(sig_bytes, pk_bytes) / 4.0

    def total_bytes(self, sig_bytes: int, pk_bytes: int) -> int:
        return self.base_bytes() + self.witness_bytes(sig_bytes, pk_bytes)


# ── 1A: Signature size sweep ──────────────────────────────────────
@dataclass
class BlockCapacityResult:
    algorithm: str
    security_level: str
    sig_bytes: int
    pk_bytes: int
    tx_weight: float
    txs_per_block: int
    effective_tps: float
    sig_fraction_of_weight: float  # What % of tx weight is just the signature
    throughput_reduction_pct: float  # vs ECDSA baseline


def run_block_capacity_sweep(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    policy: WitnessPolicy = CURRENT_SEGWIT,
) -> List[BlockCapacityResult]:
    """Compute block capacity for each PQC algorithm.

    Args:
        algorithms: List of algorithms to test (default: all).
        policy: Witness discount policy.

    Returns:
        List of BlockCapacityResult, one per algorithm.
    """
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    sizer = BitcoinTxSizer()
    baseline_txs = sizer.txs_per_block(ECDSA.sig_bytes, ECDSA.pk_bytes, policy)

    results: List[BlockCapacityResult] = []
    for alg in algorithms:
        w = sizer.tx_weight(alg.sig_bytes, alg.pk_bytes, policy)
        txs = sizer.txs_per_block(alg.sig_bytes, alg.pk_bytes, policy)
        tps = txs / BLOCK_INTERVAL_S

        # Signature contribution to weight
        witness_w = sizer.witness_bytes(alg.sig_bytes, alg.pk_bytes) * policy.witness_multiplier
        sig_frac = witness_w / w if w > 0 else 0.0

        reduction = (1.0 - txs / baseline_txs) * 100.0 if baseline_txs > 0 else 0.0

        results.append(BlockCapacityResult(
            algorithm=alg.name,
            security_level=alg.security_level,
            sig_bytes=alg.sig_bytes,
            pk_bytes=alg.pk_bytes,
            tx_weight=w,
            txs_per_block=txs,
            effective_tps=round(tps, 3),
            sig_fraction_of_weight=round(sig_frac, 4),
            throughput_reduction_pct=round(reduction, 2),
        ))
    return results


# ── 1B: Witness policy comparison ─────────────────────────────────
@dataclass
class PolicyComparisonResult:
    algorithm: str
    policy: str
    tx_weight: float
    txs_per_block: int
    effective_tps: float


def run_policy_comparison(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    policies: Optional[List[WitnessPolicy]] = None,
) -> List[PolicyComparisonResult]:
    """Compare block capacity across witness discount policies."""
    if algorithms is None:
        algorithms = ALL_ALGORITHMS
    if policies is None:
        policies = ALL_POLICIES

    sizer = BitcoinTxSizer()
    results: List[PolicyComparisonResult] = []

    for alg in algorithms:
        for pol in policies:
            w = sizer.tx_weight(alg.sig_bytes, alg.pk_bytes, pol)
            txs = sizer.txs_per_block(alg.sig_bytes, alg.pk_bytes, pol)
            tps = txs / BLOCK_INTERVAL_S
            results.append(PolicyComparisonResult(
                algorithm=alg.name,
                policy=pol.name,
                tx_weight=w,
                txs_per_block=txs,
                effective_tps=round(tps, 3),
            ))
    return results


# ── 1C: Fee market simulation ─────────────────────────────────────
@dataclass
class MempoolTx:
    """A transaction in the mempool."""
    is_pqc: bool
    fee_rate_sat_per_vbyte: float   # fee rate for priority ordering
    vsize: float                     # virtual size (weight / 4)
    weight: float
    total_fee_sat: float

    @property
    def priority(self) -> float:
        """Miner priority = fee rate (greedy by sat/vB)."""
        return self.fee_rate_sat_per_vbyte


@dataclass
class FeeMarketResult:
    """Aggregated fee market simulation result."""
    algorithm: str
    mempool_pressure: str  # "low", "medium", "high"
    pqc_adoption_pct: float
    total_txs_in_mempool: int
    block_txs_included: int
    block_fee_revenue_sat: float
    ecdsa_inclusion_rate: float
    pqc_inclusion_rate: float
    fee_premium_pct: float  # Extra % PQC users must pay for same inclusion
    pqc_txs_stuck: int


def _generate_mempool(
    n_txs: int,
    pqc_fraction: float,
    pqc_alg: PQCAlgorithm,
    seed: int = 42,
) -> List[MempoolTx]:
    """Generate a synthetic mempool with a mix of ECDSA and PQC txs."""
    rng = random.Random(seed)
    sizer = BitcoinTxSizer()
    txs: List[MempoolTx] = []

    for _ in range(n_txs):
        is_pqc = rng.random() < pqc_fraction

        if is_pqc:
            vsize = sizer.tx_vsize(pqc_alg.sig_bytes, pqc_alg.pk_bytes)
            weight = sizer.tx_weight(pqc_alg.sig_bytes, pqc_alg.pk_bytes)
        else:
            vsize = sizer.tx_vsize(ECDSA.sig_bytes, ECDSA.pk_bytes)
            weight = sizer.tx_weight(ECDSA.sig_bytes, ECDSA.pk_bytes)

        # Fee rate drawn from lognormal — realistic mempool distribution
        # Mean ~20 sat/vB with heavy tail
        fee_rate = rng.lognormvariate(3.0, 0.8)  # median ~20
        fee_rate = max(1.0, fee_rate)  # floor at 1 sat/vB

        total_fee = fee_rate * vsize
        txs.append(MempoolTx(
            is_pqc=is_pqc,
            fee_rate_sat_per_vbyte=fee_rate,
            vsize=vsize,
            weight=weight,
            total_fee_sat=total_fee,
        ))
    return txs


def _construct_block(mempool: List[MempoolTx], weight_limit: int = BLOCK_WEIGHT_LIMIT) -> List[MempoolTx]:
    """Greedy block construction: sort by fee rate descending, fill to weight limit."""
    sorted_txs = sorted(mempool, key=lambda t: t.fee_rate_sat_per_vbyte, reverse=True)
    included: List[MempoolTx] = []
    used_weight = 0.0
    for tx in sorted_txs:
        if used_weight + tx.weight <= weight_limit:
            included.append(tx)
            used_weight += tx.weight
    return included


def run_fee_market_simulation(
    pqc_alg: PQCAlgorithm,
    mempool_pressure: str = "medium",
    pqc_adoption_pct: float = 50.0,
    seed: int = 42,
) -> FeeMarketResult:
    """Simulate one block construction under given conditions.

    Args:
        pqc_alg: PQC algorithm for the PQC transactions.
        mempool_pressure: "low" (1x capacity), "medium" (3x), "high" (10x).
        pqc_adoption_pct: Percentage of mempool txs that use PQC.
        seed: RNG seed.

    Returns:
        FeeMarketResult with inclusion rates, fee premiums, etc.
    """
    sizer = BitcoinTxSizer()
    baseline_capacity = sizer.txs_per_block(ECDSA.sig_bytes, ECDSA.pk_bytes)

    pressure_map = {"low": 1.0, "medium": 3.0, "high": 10.0}
    multiplier = pressure_map.get(mempool_pressure, 3.0)
    n_txs = int(baseline_capacity * multiplier)

    pqc_fraction = pqc_adoption_pct / 100.0
    mempool = _generate_mempool(n_txs, pqc_fraction, pqc_alg, seed)
    included = _construct_block(mempool)

    # Count inclusions by type
    ecdsa_in_mempool = sum(1 for t in mempool if not t.is_pqc)
    pqc_in_mempool = sum(1 for t in mempool if t.is_pqc)
    ecdsa_included = sum(1 for t in included if not t.is_pqc)
    pqc_included = sum(1 for t in included if t.is_pqc)

    ecdsa_rate = ecdsa_included / ecdsa_in_mempool if ecdsa_in_mempool > 0 else 0.0
    pqc_rate = pqc_included / pqc_in_mempool if pqc_in_mempool > 0 else 0.0

    total_revenue = sum(t.total_fee_sat for t in included)

    # Fee premium: median fee rate of included PQC vs included ECDSA
    ecdsa_rates = sorted([t.fee_rate_sat_per_vbyte for t in included if not t.is_pqc])
    pqc_rates = sorted([t.fee_rate_sat_per_vbyte for t in included if t.is_pqc])
    median_ecdsa = ecdsa_rates[len(ecdsa_rates) // 2] if ecdsa_rates else 0.0
    median_pqc = pqc_rates[len(pqc_rates) // 2] if pqc_rates else 0.0
    fee_premium = ((median_pqc - median_ecdsa) / median_ecdsa * 100.0) if median_ecdsa > 0 else 0.0

    pqc_stuck = pqc_in_mempool - pqc_included

    return FeeMarketResult(
        algorithm=pqc_alg.name,
        mempool_pressure=mempool_pressure,
        pqc_adoption_pct=pqc_adoption_pct,
        total_txs_in_mempool=n_txs,
        block_txs_included=len(included),
        block_fee_revenue_sat=round(total_revenue, 2),
        ecdsa_inclusion_rate=round(ecdsa_rate, 4),
        pqc_inclusion_rate=round(pqc_rate, 4),
        fee_premium_pct=round(fee_premium, 2),
        pqc_txs_stuck=pqc_stuck,
    )


# ── Full Bitcoin analysis ──────────────────────────────────────────
@dataclass
class BitcoinAnalysisResults:
    """Container for all Bitcoin PQC analysis outputs."""
    block_capacity: List[BlockCapacityResult]
    policy_comparison: List[PolicyComparisonResult]
    fee_market: List[FeeMarketResult]


def run_full_bitcoin_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    seed: int = 42,
) -> BitcoinAnalysisResults:
    """Run all Bitcoin PQC analyses.

    Args:
        algorithms: Algorithms to analyse (default: all).
        seed: RNG seed for fee market simulation.

    Returns:
        BitcoinAnalysisResults with all sub-analyses.
    """
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    # 1A: Block capacity under current SegWit
    capacity = run_block_capacity_sweep(algorithms)

    # 1B: Policy comparison
    policy = run_policy_comparison(algorithms)

    # 1C: Fee market — sweep pressure × algorithm (PQC only)
    fee_results: List[FeeMarketResult] = []
    pqc_only = [a for a in algorithms if a.family != "ecdsa"]
    for alg in pqc_only:
        for pressure in ["low", "medium", "high"]:
            result = run_fee_market_simulation(
                pqc_alg=alg,
                mempool_pressure=pressure,
                pqc_adoption_pct=50.0,
                seed=seed,
            )
            fee_results.append(result)

    return BitcoinAnalysisResults(
        block_capacity=capacity,
        policy_comparison=policy,
        fee_market=fee_results,
    )
