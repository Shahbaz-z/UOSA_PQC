"""Ethereum PQC impact analysis — gas costs, EIP-1559, consensus layer, validator economics.

Analytical models covering both the execution layer (gas, block fill, fees)
and the consensus layer (attestation sizes, P2P bandwidth, slot timing).

All computations are deterministic and complete in < 5 s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    BLS_12_381,
    ECDSA,
    PQC_ALGORITHMS,
    PQCAlgorithm,
)


# ── Constants ───────────────────────────────────────────────────────
GAS_LIMIT = 30_000_000        # Block gas limit
BLOCK_TIME_S = 12             # Seconds per slot
SLOTS_PER_EPOCH = 32
EPOCHS_PER_DAY = 225          # ~225 epochs per day

# Transaction type base gas costs (excluding sig verification)
SIMPLE_TRANSFER_GAS = 21_000
ERC20_TRANSFER_GAS = 65_000
COMPLEX_CALL_GAS = 200_000

# Calldata gas
CALLDATA_GAS_NONZERO = 16     # per non-zero byte
CALLDATA_GAS_ZERO = 4         # per zero byte
ZERO_BYTE_FRACTION = 0.05     # ~5% zeros in sig/pk data

# Consensus layer
CURRENT_VALIDATORS = 1_000_000
COMMITTEE_SIZE = 512           # Validators per slot committee
ATTESTATION_DEADLINE_S = 4.0   # Must propagate within 4s
TYPICAL_BANDWIDTH_MBPS = 100   # Typical validator bandwidth
BLS_AGG_SIG_BYTES = 96         # Single aggregated BLS signature
BLS_AGG_PK_BYTES = 48          # BLS public key

# Current attestation: bitfield + aggregated sig
CURRENT_ATTESTATION_BYTES = 128 + BLS_AGG_SIG_BYTES  # ~224 bytes per committee


# ── Execution layer helpers ────────────────────────────────────────
def _calldata_gas(data_bytes: int) -> int:
    """Gas cost for data_bytes of calldata."""
    zero = int(data_bytes * ZERO_BYTE_FRACTION)
    nonzero = data_bytes - zero
    return nonzero * CALLDATA_GAS_NONZERO + zero * CALLDATA_GAS_ZERO


def _sig_overhead_gas(alg: PQCAlgorithm) -> int:
    """Additional gas vs ECDSA for signature verification + calldata.

    Returns the NET overhead (PQC gas - ECDSA gas).
    """
    # ECDSA calldata cost (sig + pk)
    ecdsa_calldata = _calldata_gas(ECDSA.sig_bytes + ECDSA.pk_bytes)
    ecdsa_verify = ECDSA.verify_gas_estimate
    ecdsa_total = ecdsa_calldata + ecdsa_verify

    # PQC calldata cost
    pqc_calldata = _calldata_gas(alg.sig_bytes + alg.pk_bytes)
    pqc_verify = alg.verify_gas_estimate
    pqc_total = pqc_calldata + pqc_verify

    return pqc_total - ecdsa_total


# ── 2A: Gas cost analysis ─────────────────────────────────────────
@dataclass
class GasCostResult:
    algorithm: str
    security_level: str
    verify_gas: int
    calldata_gas: int
    total_overhead_gas: int     # Net vs ECDSA
    simple_txs_per_block: int
    erc20_txs_per_block: int
    complex_txs_per_block: int
    simple_tps: float
    erc20_tps: float
    complex_tps: float
    throughput_reduction_simple_pct: float
    throughput_reduction_erc20_pct: float
    sig_gas_fraction: float    # % of tx gas consumed by sig


def run_gas_cost_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
) -> List[GasCostResult]:
    """Compute per-block capacity for each tx type × algorithm."""
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    # Baselines (ECDSA)
    ecdsa_cd = _calldata_gas(ECDSA.sig_bytes + ECDSA.pk_bytes)
    ecdsa_total_simple = SIMPLE_TRANSFER_GAS + ecdsa_cd + ECDSA.verify_gas_estimate
    ecdsa_total_erc20 = ERC20_TRANSFER_GAS + ecdsa_cd + ECDSA.verify_gas_estimate
    baseline_simple = GAS_LIMIT // ecdsa_total_simple
    baseline_erc20 = GAS_LIMIT // ecdsa_total_erc20

    results: List[GasCostResult] = []
    for alg in algorithms:
        cd = _calldata_gas(alg.sig_bytes + alg.pk_bytes)
        verify = alg.verify_gas_estimate
        sig_gas = cd + verify

        overhead = _sig_overhead_gas(alg) if alg.family != "ecdsa" else 0

        simple_gas = SIMPLE_TRANSFER_GAS + sig_gas
        erc20_gas = ERC20_TRANSFER_GAS + sig_gas
        complex_gas = COMPLEX_CALL_GAS + sig_gas

        simple_n = GAS_LIMIT // simple_gas if simple_gas > 0 else 0
        erc20_n = GAS_LIMIT // erc20_gas if erc20_gas > 0 else 0
        complex_n = GAS_LIMIT // complex_gas if complex_gas > 0 else 0

        red_simple = (1 - simple_n / baseline_simple) * 100 if baseline_simple > 0 else 0
        red_erc20 = (1 - erc20_n / baseline_erc20) * 100 if baseline_erc20 > 0 else 0

        results.append(GasCostResult(
            algorithm=alg.name,
            security_level=alg.security_level,
            verify_gas=verify,
            calldata_gas=cd,
            total_overhead_gas=overhead,
            simple_txs_per_block=simple_n,
            erc20_txs_per_block=erc20_n,
            complex_txs_per_block=complex_n,
            simple_tps=round(simple_n / BLOCK_TIME_S, 2),
            erc20_tps=round(erc20_n / BLOCK_TIME_S, 2),
            complex_tps=round(complex_n / BLOCK_TIME_S, 2),
            throughput_reduction_simple_pct=round(red_simple, 2),
            throughput_reduction_erc20_pct=round(red_erc20, 2),
            sig_gas_fraction=round(sig_gas / simple_gas, 4) if simple_gas > 0 else 0.0,
        ))
    return results


# ── 2B: EIP-1559 base fee dynamics ────────────────────────────────
@dataclass
class EIP1559Result:
    algorithm: str
    equilibrium_base_fee_gwei: float
    base_fee_multiplier: float     # vs ECDSA baseline
    avg_block_utilization: float
    avg_user_tx_cost_gwei: float
    blocks_over_target: int        # out of 1000


def simulate_eip1559(
    alg: PQCAlgorithm,
    demand_txs_per_block: int = 150,
    n_blocks: int = 1_000,
    initial_base_fee_gwei: float = 30.0,
    max_base_fee_gwei: float = 1_000_000.0,
) -> EIP1559Result:
    """Simulate EIP-1559 base fee adjustment over n_blocks.

    Includes demand elasticity: as base fee rises, some users are
    priced out, reducing effective demand (log-linear demand curve).

    Args:
        alg: Signature algorithm.
        demand_txs_per_block: Peak tx arrival rate at minimum fee.
        n_blocks: Number of blocks to simulate.
        initial_base_fee_gwei: Starting base fee.
        max_base_fee_gwei: Cap to prevent unbounded growth.

    Returns:
        EIP1559Result with equilibrium metrics.
    """
    cd = _calldata_gas(alg.sig_bytes + alg.pk_bytes)
    verify = alg.verify_gas_estimate
    simple_gas = SIMPLE_TRANSFER_GAS + cd + verify

    target_gas = GAS_LIMIT // 2  # EIP-1559 target = 50% of limit
    base_fee = initial_base_fee_gwei
    base_fees: List[float] = []
    utilizations: List[float] = []
    over_target = 0

    # Reference base fee for demand elasticity
    ref_fee = initial_base_fee_gwei

    for _ in range(n_blocks):
        # Demand elasticity: users drop off as fees rise
        # At 10× the reference fee, demand halves; at 100×, drops to ~33%
        fee_ratio = base_fee / ref_fee if ref_fee > 0 else 1.0
        elasticity = 1.0 / (1.0 + math.log1p(max(fee_ratio - 1.0, 0.0)))
        effective_demand = int(demand_txs_per_block * elasticity)

        # Gas demanded this block
        gas_demanded = effective_demand * simple_gas
        gas_used = min(gas_demanded, GAS_LIMIT)
        utilization = gas_used / GAS_LIMIT

        utilizations.append(utilization)
        base_fees.append(base_fee)

        if gas_used > target_gas:
            over_target += 1

        # EIP-1559 adjustment
        delta = (gas_used - target_gas) / target_gas
        delta = max(-1.0, min(1.0, delta))
        base_fee *= (1.0 + 0.125 * delta)
        base_fee = max(1.0, min(max_base_fee_gwei, base_fee))

    eq_fee = sum(base_fees[-100:]) / 100  # Last 100 blocks
    avg_util = sum(utilizations) / len(utilizations)
    # User cost = base_fee * gas per tx (in gwei)
    avg_cost = eq_fee * simple_gas

    return EIP1559Result(
        algorithm=alg.name,
        equilibrium_base_fee_gwei=round(eq_fee, 4),
        base_fee_multiplier=0.0,  # Filled in by caller
        avg_block_utilization=round(avg_util, 4),
        avg_user_tx_cost_gwei=round(avg_cost, 2),
        blocks_over_target=over_target,
    )


def run_eip1559_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    demand_txs_per_block: int = 150,
) -> List[EIP1559Result]:
    """Run EIP-1559 simulation for each algorithm."""
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    results = []
    baseline_fee: Optional[float] = None

    for alg in algorithms:
        r = simulate_eip1559(alg, demand_txs_per_block=demand_txs_per_block)
        if baseline_fee is None:
            baseline_fee = r.equilibrium_base_fee_gwei
        r.base_fee_multiplier = round(
            r.equilibrium_base_fee_gwei / baseline_fee if baseline_fee > 0 else 0.0, 3
        )
        results.append(r)
    return results


# ── 2C: Consensus layer — attestation & P2P ───────────────────────
@dataclass
class ConsensusLayerResult:
    algorithm: str
    individual_attestation_bytes: int
    committee_attestation_bytes: int   # For one committee (no aggregation)
    attestation_multiplier: float      # vs BLS aggregated
    bandwidth_required_mbps: float     # To propagate within deadline
    slot_timing_feasible: bool         # Can propagate within deadline at typical BW?
    beacon_block_overhead_kb: float    # Extra KB per beacon block


def run_consensus_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    committee_size: int = COMMITTEE_SIZE,
    bandwidth_mbps: float = TYPICAL_BANDWIDTH_MBPS,
) -> List[ConsensusLayerResult]:
    """Assess PQC impact on the beacon chain consensus layer.

    Without BLS-style aggregation, each committee member's attestation
    must include an individual signature.
    """
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    results: List[ConsensusLayerResult] = []

    for alg in algorithms:
        if alg.family == "ecdsa":
            # Use BLS as the baseline for consensus
            ind_att = BLS_AGG_SIG_BYTES + 128  # sig + attestation data
            committee_total = CURRENT_ATTESTATION_BYTES  # Aggregated
            multiplier = 1.0
        else:
            # PQC: no aggregation → each validator signs individually
            ind_att = alg.sig_bytes + 128  # sig + attestation data
            committee_total = committee_size * ind_att
            multiplier = committee_total / CURRENT_ATTESTATION_BYTES

        # Bandwidth: must propagate committee attestation within deadline
        # 64 committees per slot (one per slot for each committee index)
        # But the most demanding case is: all committee attestations for this slot
        total_bytes_per_slot = committee_total * 64  # 64 committees × committee size
        bits_per_second = (total_bytes_per_slot * 8) / ATTESTATION_DEADLINE_S
        bw_mbps = bits_per_second / 1e6

        feasible = bw_mbps <= bandwidth_mbps

        # Beacon block overhead (vs current)
        if alg.family == "ecdsa":
            overhead_kb = 0.0
        else:
            current_total = CURRENT_ATTESTATION_BYTES * 64
            overhead_bytes = total_bytes_per_slot - current_total
            overhead_kb = overhead_bytes / 1024

        results.append(ConsensusLayerResult(
            algorithm=alg.name,
            individual_attestation_bytes=ind_att,
            committee_attestation_bytes=committee_total,
            attestation_multiplier=round(multiplier, 2),
            bandwidth_required_mbps=round(bw_mbps, 2),
            slot_timing_feasible=feasible,
            beacon_block_overhead_kb=round(overhead_kb, 2),
        ))
    return results


# ── 2D: Validator economics ───────────────────────────────────────
@dataclass
class ValidatorEconResult:
    algorithm: str
    extra_bandwidth_gb_per_month: float
    extra_storage_gb_per_month: float
    min_bandwidth_requirement_mbps: float
    pct_validators_below_requirement: float  # Centralization risk


def run_validator_economics(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    committee_size: int = COMMITTEE_SIZE,
) -> List[ValidatorEconResult]:
    """Compute validator resource requirements under PQC."""
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    # Bandwidth distribution of validators (assumed lognormal)
    # Median ~100 Mbps, long tail of low-BW validators
    # We model percentiles: 10% have < 25 Mbps, 25% have < 50 Mbps
    bw_thresholds = [
        (25, 0.10),   # 10% of validators below 25 Mbps
        (50, 0.25),   # 25% below 50 Mbps
        (100, 0.50),  # 50% below 100 Mbps
    ]

    results: List[ValidatorEconResult] = []

    for alg in algorithms:
        if alg.family == "ecdsa":
            results.append(ValidatorEconResult(
                algorithm=alg.name,
                extra_bandwidth_gb_per_month=0.0,
                extra_storage_gb_per_month=0.0,
                min_bandwidth_requirement_mbps=0.0,
                pct_validators_below_requirement=0.0,
            ))
            continue

        # Per-slot attestation data
        ind_att = alg.sig_bytes + 128
        committee_total = committee_size * ind_att
        total_per_slot = committee_total * 64  # 64 committees

        # Current per-slot attestation data
        current_per_slot = CURRENT_ATTESTATION_BYTES * 64

        # Extra bytes per slot
        extra_per_slot = total_per_slot - current_per_slot

        # Extra bandwidth per month (both send + receive)
        slots_per_month = 216_000  # 12s slots × 30 days
        extra_bytes_month = extra_per_slot * slots_per_month * 2  # bidirectional
        extra_gb_month = extra_bytes_month / (1024 ** 3)

        # Storage: beacon chain state growth
        extra_storage_month = extra_per_slot * slots_per_month / (1024 ** 3)

        # Minimum bandwidth requirement
        bits_per_second = (total_per_slot * 8) / ATTESTATION_DEADLINE_S
        min_bw_mbps = bits_per_second / 1e6

        # % validators that can't meet this
        pct_below = 0.0
        for threshold, pct in bw_thresholds:
            if min_bw_mbps > threshold:
                pct_below = max(pct_below, pct)

        results.append(ValidatorEconResult(
            algorithm=alg.name,
            extra_bandwidth_gb_per_month=round(extra_gb_month, 2),
            extra_storage_gb_per_month=round(extra_storage_month, 2),
            min_bandwidth_requirement_mbps=round(min_bw_mbps, 2),
            pct_validators_below_requirement=round(pct_below * 100, 1),
        ))
    return results


# ── Full Ethereum analysis ─────────────────────────────────────────
@dataclass
class EthereumAnalysisResults:
    gas_cost: List[GasCostResult]
    eip1559: List[EIP1559Result]
    consensus: List[ConsensusLayerResult]
    validator_economics: List[ValidatorEconResult]


def run_full_ethereum_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
) -> EthereumAnalysisResults:
    """Run all Ethereum PQC analyses."""
    if algorithms is None:
        algorithms = ALL_ALGORITHMS

    return EthereumAnalysisResults(
        gas_cost=run_gas_cost_analysis(algorithms),
        eip1559=run_eip1559_analysis(algorithms),
        consensus=run_consensus_analysis(algorithms),
        validator_economics=run_validator_economics(algorithms),
    )
