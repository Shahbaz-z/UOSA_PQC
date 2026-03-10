"""PQC migration transition model — mixed ECDSA/BLS + PQC coexistence.

Models the transition period where legacy and PQC transactions coexist
on both Bitcoin and Ethereum, computing capacity, fees, and critical
thresholds as adoption increases from 0 → 100%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    ECDSA,
    BLS_12_381,
    PQC_ALGORITHMS,
    PQCAlgorithm,
)
from analysis.bitcoin_pqc_analysis import (
    BLOCK_WEIGHT_LIMIT,
    BLOCK_INTERVAL_S,
    BitcoinTxSizer,
    CURRENT_SEGWIT,
    _generate_mempool,
    _construct_block,
)
from analysis.ethereum_pqc_analysis import (
    GAS_LIMIT,
    BLOCK_TIME_S,
    SIMPLE_TRANSFER_GAS,
    ERC20_TRANSFER_GAS,
    COMPLEX_CALL_GAS,
    CALLDATA_GAS_NONZERO,
    CALLDATA_GAS_ZERO,
    ZERO_BYTE_FRACTION,
    CURRENT_ATTESTATION_BYTES,
    COMMITTEE_SIZE,
    ATTESTATION_DEADLINE_S,
    TYPICAL_BANDWIDTH_MBPS,
    _calldata_gas,
)


# ── Adoption sweep points ──────────────────────────────────────────
ADOPTION_STEPS = list(range(0, 101, 5))  # 0%, 5%, 10%, ... , 100%


# ── Bitcoin migration ──────────────────────────────────────────────
@dataclass
class BitcoinMigrationPoint:
    """One data point in the Bitcoin migration curve."""
    algorithm: str
    pqc_adoption_pct: float
    txs_per_block: int
    effective_tps: float
    ecdsa_inclusion_rate: float
    pqc_inclusion_rate: float
    fee_premium_pct: float
    block_weight_utilization: float


@dataclass
class BitcoinMigrationResult:
    """Full Bitcoin migration analysis for one algorithm."""
    algorithm: str
    curve: List[BitcoinMigrationPoint]
    critical_50pct_tps_threshold: Optional[float]  # Adoption % where TPS drops 50%
    fee_2x_threshold: Optional[float]               # Adoption % where PQC fee premium > 100%


def run_bitcoin_migration(
    alg: PQCAlgorithm,
    mempool_pressure: str = "medium",
    seed: int = 42,
) -> BitcoinMigrationResult:
    """Sweep PQC adoption from 0→100% on Bitcoin.

    At each adoption level, construct a block from a mixed mempool
    and measure capacity + fee dynamics.
    """
    sizer = BitcoinTxSizer()
    baseline_capacity = sizer.txs_per_block(ECDSA.sig_bytes, ECDSA.pk_bytes)
    baseline_tps = baseline_capacity / BLOCK_INTERVAL_S

    pressure_map = {"low": 1.0, "medium": 3.0, "high": 10.0}
    multiplier = pressure_map.get(mempool_pressure, 3.0)
    n_txs = int(baseline_capacity * multiplier)

    curve: List[BitcoinMigrationPoint] = []
    tps_50_threshold: Optional[float] = None
    fee_2x_threshold: Optional[float] = None

    for adoption in ADOPTION_STEPS:
        pqc_frac = adoption / 100.0
        mempool = _generate_mempool(n_txs, pqc_frac, alg, seed + adoption)
        included = _construct_block(mempool)

        txs_in_block = len(included)
        tps = txs_in_block / BLOCK_INTERVAL_S

        # Weight utilization
        total_weight = sum(t.weight for t in included)
        weight_util = total_weight / BLOCK_WEIGHT_LIMIT

        # Inclusion rates
        ecdsa_mem = sum(1 for t in mempool if not t.is_pqc)
        pqc_mem = sum(1 for t in mempool if t.is_pqc)
        ecdsa_inc = sum(1 for t in included if not t.is_pqc)
        pqc_inc = sum(1 for t in included if t.is_pqc)

        ecdsa_rate = ecdsa_inc / ecdsa_mem if ecdsa_mem > 0 else 0.0
        pqc_rate = pqc_inc / pqc_mem if pqc_mem > 0 else 0.0

        # Fee premium
        ecdsa_rates = sorted([t.fee_rate_sat_per_vbyte for t in included if not t.is_pqc])
        pqc_rates = sorted([t.fee_rate_sat_per_vbyte for t in included if t.is_pqc])
        med_ecdsa = ecdsa_rates[len(ecdsa_rates) // 2] if ecdsa_rates else 0.0
        med_pqc = pqc_rates[len(pqc_rates) // 2] if pqc_rates else 0.0
        premium = ((med_pqc - med_ecdsa) / med_ecdsa * 100) if med_ecdsa > 0 else 0.0

        point = BitcoinMigrationPoint(
            algorithm=alg.name,
            pqc_adoption_pct=float(adoption),
            txs_per_block=txs_in_block,
            effective_tps=round(tps, 3),
            ecdsa_inclusion_rate=round(ecdsa_rate, 4),
            pqc_inclusion_rate=round(pqc_rate, 4),
            fee_premium_pct=round(premium, 2),
            block_weight_utilization=round(weight_util, 4),
        )
        curve.append(point)

        # Threshold detection
        if tps_50_threshold is None and tps < baseline_tps * 0.5:
            tps_50_threshold = float(adoption)
        if fee_2x_threshold is None and premium > 100.0:
            fee_2x_threshold = float(adoption)

    return BitcoinMigrationResult(
        algorithm=alg.name,
        curve=curve,
        critical_50pct_tps_threshold=tps_50_threshold,
        fee_2x_threshold=fee_2x_threshold,
    )


# ── Ethereum migration ─────────────────────────────────────────────
@dataclass
class EthereumMigrationPoint:
    """One data point in the Ethereum migration curve."""
    algorithm: str
    pqc_adoption_pct: float
    # Execution layer
    effective_tps: float
    avg_gas_per_tx: float
    block_utilization: float
    base_fee_gwei: float
    # Consensus layer (only at full PQC for consensus transition)
    consensus_phase: str  # "bls" or "pqc"
    attestation_bandwidth_mbps: float


@dataclass
class EthereumMigrationResult:
    """Full Ethereum migration analysis for one algorithm."""
    algorithm: str
    curve: List[EthereumMigrationPoint]
    gas_limit_increase_threshold: Optional[float]  # Adoption % where gas limit increase needed
    consensus_feasibility: bool  # Can consensus layer handle this PQC at typical BW?


def _weighted_gas_per_tx(
    pqc_frac: float,
    alg: PQCAlgorithm,
    tx_mix: Dict[str, float],
) -> float:
    """Compute weighted average gas per tx in a mixed ECDSA+PQC population.

    tx_mix: {"simple": 0.6, "erc20": 0.3, "complex": 0.1}
    """
    base_gas_map = {
        "simple": SIMPLE_TRANSFER_GAS,
        "erc20": ERC20_TRANSFER_GAS,
        "complex": COMPLEX_CALL_GAS,
    }

    ecdsa_cd = _calldata_gas(ECDSA.sig_bytes + ECDSA.pk_bytes)
    pqc_cd = _calldata_gas(alg.sig_bytes + alg.pk_bytes)

    total = 0.0
    for tx_type, fraction in tx_mix.items():
        base = base_gas_map.get(tx_type, SIMPLE_TRANSFER_GAS)

        # ECDSA portion
        ecdsa_gas = base + ecdsa_cd + ECDSA.verify_gas_estimate
        # PQC portion
        pqc_gas = base + pqc_cd + alg.verify_gas_estimate

        # Weighted by adoption and tx type fraction
        avg = (1 - pqc_frac) * ecdsa_gas + pqc_frac * pqc_gas
        total += fraction * avg

    return total


def run_ethereum_migration(
    alg: PQCAlgorithm,
    tx_mix: Optional[Dict[str, float]] = None,
    demand_txs_per_block: int = 150,
) -> EthereumMigrationResult:
    """Sweep PQC adoption from 0→100% on Ethereum.

    Models both execution layer (tx gas) and consensus layer (attestations).
    Consensus transition is modeled as two phases:
    1. Execution-only PQC (consensus still uses BLS)
    2. Full PQC (both execution and consensus)
    """
    if tx_mix is None:
        tx_mix = {"simple": 0.60, "erc20": 0.30, "complex": 0.10}

    target_gas = GAS_LIMIT // 2
    curve: List[EthereumMigrationPoint] = []
    gas_threshold: Optional[float] = None

    # Baseline TPS
    baseline_gas_per_tx = _weighted_gas_per_tx(0.0, alg, tx_mix)
    baseline_tps = (GAS_LIMIT // int(baseline_gas_per_tx)) / BLOCK_TIME_S

    for adoption in ADOPTION_STEPS:
        pqc_frac = adoption / 100.0

        # Execution layer
        avg_gas = _weighted_gas_per_tx(pqc_frac, alg, tx_mix)
        txs_per_block = GAS_LIMIT // int(avg_gas) if avg_gas > 0 else 0
        tps = txs_per_block / BLOCK_TIME_S

        gas_used = demand_txs_per_block * avg_gas
        utilization = min(gas_used / GAS_LIMIT, 1.0)

        # EIP-1559 base fee (simplified single-step equilibrium)
        # If demand > capacity, base fee rises
        if gas_used > target_gas:
            delta = (gas_used - target_gas) / target_gas
            base_fee = 30.0 * (1.0 + 0.125 * min(delta, 8.0))  # Cap multiplier
        else:
            delta = (target_gas - gas_used) / target_gas
            base_fee = 30.0 * (1.0 - 0.125 * min(delta, 1.0))
        base_fee = max(1.0, base_fee)

        # Consensus layer — execution-only PQC (BLS still for consensus)
        att_bw = (CURRENT_ATTESTATION_BYTES * 64 * 8) / ATTESTATION_DEADLINE_S / 1e6

        point_bls = EthereumMigrationPoint(
            algorithm=alg.name,
            pqc_adoption_pct=float(adoption),
            effective_tps=round(tps, 3),
            avg_gas_per_tx=round(avg_gas, 0),
            block_utilization=round(utilization, 4),
            base_fee_gwei=round(base_fee, 4),
            consensus_phase="bls",
            attestation_bandwidth_mbps=round(att_bw, 2),
        )
        curve.append(point_bls)

        # Full PQC consensus — only at this adoption level
        if alg.family not in ("ecdsa", "bls"):
            ind_att = alg.sig_bytes + 128
            committee_total = COMMITTEE_SIZE * ind_att
            total_per_slot = committee_total * 64
            pqc_bw = (total_per_slot * 8) / ATTESTATION_DEADLINE_S / 1e6

            point_pqc = EthereumMigrationPoint(
                algorithm=alg.name,
                pqc_adoption_pct=float(adoption),
                effective_tps=round(tps, 3),
                avg_gas_per_tx=round(avg_gas, 0),
                block_utilization=round(utilization, 4),
                base_fee_gwei=round(base_fee, 4),
                consensus_phase="pqc",
                attestation_bandwidth_mbps=round(pqc_bw, 2),
            )
            curve.append(point_pqc)

        # Threshold: when do we need a gas limit increase?
        if gas_threshold is None and tps < baseline_tps * 0.8:
            gas_threshold = float(adoption)

    # Consensus feasibility at 100% PQC
    if alg.family not in ("ecdsa", "bls"):
        ind_att = alg.sig_bytes + 128
        total_per_slot = COMMITTEE_SIZE * ind_att * 64
        full_pqc_bw = (total_per_slot * 8) / ATTESTATION_DEADLINE_S / 1e6
        consensus_ok = full_pqc_bw <= TYPICAL_BANDWIDTH_MBPS
    else:
        consensus_ok = True

    return EthereumMigrationResult(
        algorithm=alg.name,
        curve=curve,
        gas_limit_increase_threshold=gas_threshold,
        consensus_feasibility=consensus_ok,
    )


# ── Full migration analysis ────────────────────────────────────────
@dataclass
class MigrationResults:
    bitcoin: List[BitcoinMigrationResult]
    ethereum: List[EthereumMigrationResult]


def run_full_migration_analysis(
    algorithms: Optional[List[PQCAlgorithm]] = None,
    seed: int = 42,
) -> MigrationResults:
    """Run migration analysis for all PQC algorithms on both chains."""
    if algorithms is None:
        algorithms = [a for a in ALL_ALGORITHMS if a.family not in ("ecdsa", "bls")]

    btc_results: List[BitcoinMigrationResult] = []
    eth_results: List[EthereumMigrationResult] = []

    for alg in algorithms:
        btc_results.append(run_bitcoin_migration(alg, seed=seed))
        eth_results.append(run_ethereum_migration(alg))

    return MigrationResults(bitcoin=btc_results, ethereum=eth_results)
