"""Rational validator block-building strategy under PQC.

Validators maximise fee revenue per unit of resource consumed. Under PQC,
resource costs diverge dramatically by signature algorithm:
  - Falcon-512 has fast verify → lower compute cost → higher fee/CU ratio
  - SLH-DSA has very slow verify → high compute cost → lower fee/CU ratio

This creates an economic selection pressure:
  1. Validators prefer Falcon-512 over SLH-DSA-128s even if they pay the
     same absolute fee, because Falcon txs cost less to include.
  2. This is a "censorship incentive": SLH-DSA users must pay a significant
     premium to achieve the same inclusion probability.

The fee premium required to equalise priority scores (i.e. achieve the same
probability of inclusion as a classical ECDSA tx at baseline fees) is the
"censorship threshold" — a key metric from PLAN.md.

References:
    - Bitcoin fee selection: https://bitcoinops.org/en/topics/fee-estimation/
    - Ethereum priority fees: https://eips.ethereum.org/EIPS/eip-1559
    - Solana compute budget: https://docs.solana.com/developing/programming-model/runtime
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Resource cost tables (per chain, per algorithm)
# ---------------------------------------------------------------------------

# Weight units (Bitcoin): proportional to verification CPU time
# Maps algorithm → verification time in µs (from liboqs benchmarks)
# Source: https://openquantumsafe.org/benchmarking/
VERIFY_TIME_US: Dict[str, float] = {
    "ECDSA":         60.0,
    "Schnorr":       60.0,
    "Ed25519":       60.0,
    "BLS12-381":    750.0,
    "ML-DSA-44":    300.0,
    "ML-DSA-65":    420.0,
    "ML-DSA-87":    580.0,
    "Falcon-512":    80.0,   # fast verify
    "Falcon-1024":  170.0,
    "SLH-DSA-128s": 6_000.0,  # very slow
    "SLH-DSA-128f":  120.0,
    "SLH-DSA-192s": 9_000.0,
    "SLH-DSA-192f":  180.0,
    "SLH-DSA-256s": 14_000.0,
    "SLH-DSA-256f":   270.0,
    "Hybrid-Ed25519+ML-DSA-44":  360.0,
    "Hybrid-Ed25519+ML-DSA-65":  480.0,
    "Hybrid-Ed25519+ML-DSA-87":  640.0,
    "Hybrid-Ed25519+Falcon-512": 140.0,
    "Hybrid-Ed25519+Falcon-1024":230.0,
}

# Solana compute units per signature verification
# (imported from solana_specific to avoid duplication)
def _solana_cu(algo: str) -> int:
    from simulator.chains.solana_specific import CU_COSTS
    return CU_COSTS.get(algo, 8_000)


# Ethereum gas per verification
# (imported from ethereum_specific)
def _eth_gas(algo: str) -> int:
    from simulator.chains.ethereum_specific import PQC_VERIFICATION_GAS
    return PQC_VERIFICATION_GAS.get(algo, 3_000)


# ---------------------------------------------------------------------------
# Transaction representation
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """Minimal transaction representation for block-building decisions.

    Attributes:
        tx_id:           Unique transaction identifier.
        sig_algorithm:   Signature algorithm used.
        fee:             Absolute fee paid (satoshis / gwei / lamports).
        size_bytes:      Transaction wire size in bytes.
        weight_units:    Bitcoin weight units (= size for Ethereum/Solana).
        gas_used:        Ethereum gas used (or 0 for other chains).
        compute_units:   Solana compute units used (or 0 for other chains).
        verify_time_us:  Estimated signature verification time in microseconds.
    """

    tx_id: str
    sig_algorithm: str
    fee: float
    size_bytes: int
    weight_units: int   = 0
    gas_used: int       = 0
    compute_units: int  = 0
    verify_time_us: float = 60.0

    def __post_init__(self) -> None:
        if self.verify_time_us == 60.0:
            self.verify_time_us = VERIFY_TIME_US.get(self.sig_algorithm, 60.0)

    def fee_per_byte(self) -> float:
        """Fee per wire byte (used by Bitcoin compact-block scoring)."""
        return self.fee / self.size_bytes if self.size_bytes > 0 else 0.0

    def fee_per_weight_unit(self) -> float:
        """Fee per weight unit (Bitcoin sat/vbyte equivalent)."""
        wu = self.weight_units or self.size_bytes
        return self.fee / wu if wu > 0 else 0.0

    def fee_per_gas(self) -> float:
        """Priority fee per gas unit (Ethereum gwei/gas)."""
        return self.fee / self.gas_used if self.gas_used > 0 else 0.0

    def fee_per_compute_unit(self) -> float:
        """Priority fee per compute unit (Solana)."""
        return self.fee / self.compute_units if self.compute_units > 0 else 0.0

    def fee_per_verify_us(self) -> float:
        """Fee per microsecond of verification time.

        This is the CPU-efficiency metric: a high value means the tx generates
        more fee revenue per CPU cycle consumed during block validation.
        """
        return self.fee / self.verify_time_us if self.verify_time_us > 0 else 0.0


# ---------------------------------------------------------------------------
# BlockBuilder
# ---------------------------------------------------------------------------

@dataclass
class BlockBuilder:
    """Rational validator block-building strategy under PQC.

    Scores transactions by their fee-per-resource-unit and greedily
    selects the highest-scoring transactions until the block is full.

    Attributes:
        chain:                  Target chain ("bitcoin", "ethereum", "solana").
        sig_preference_model:   Scoring metric to use.
            "fee_per_byte"         — sat/vbyte (Bitcoin without SegWit discount)
            "fee_per_weight_unit"  — sat/WU (Bitcoin with SegWit accounting)
            "fee_per_gas"          — gwei/gas (Ethereum)
            "fee_per_compute_unit" — lamports/CU (Solana)
            "fee_per_verify_us"    — fee/CPU-µs (chain-agnostic efficiency)
        classical_algo:         Reference classical algorithm for baseline scoring.
    """

    chain: str                    = "ethereum"
    sig_preference_model: str     = "fee_per_gas"
    classical_algo: str           = "ECDSA"

    # Chain-specific block limits (used for capacity checks)
    BLOCK_LIMITS: Dict[str, Dict] = field(default_factory=lambda: {
        "bitcoin":  {"weight_units": 4_000_000},
        "ethereum": {"gas": 30_000_000},
        "solana":   {"bytes": 6_291_456, "compute_units": 48_000_000},
    })

    def score_transaction(self, tx: Transaction) -> float:
        """Compute a priority score for a transaction.

        Higher score → higher likelihood of inclusion.

        Args:
            tx: Transaction to score.

        Returns:
            Priority score (higher is better).
        """
        model = self.sig_preference_model

        if model == "fee_per_byte":
            return tx.fee_per_byte()
        if model == "fee_per_weight_unit":
            return tx.fee_per_weight_unit()
        if model == "fee_per_gas":
            return tx.fee_per_gas()
        if model == "fee_per_compute_unit":
            return tx.fee_per_compute_unit()
        if model == "fee_per_verify_us":
            return tx.fee_per_verify_us()

        # Default: fee per byte
        return tx.fee_per_byte()

    def _capacity_remaining(
        self,
        included: List[Transaction],
        block_limit: Optional[Dict] = None,
    ) -> bool:
        """Check whether there is capacity in the block for more transactions.

        Args:
            included:    Transactions already included.
            block_limit: Override block limits.

        Returns:
            True if capacity remains.
        """
        limits = block_limit or self.BLOCK_LIMITS.get(self.chain, {"bytes": 6_291_456})

        if "weight_units" in limits:
            used = sum(tx.weight_units or tx.size_bytes for tx in included)
            return used < limits["weight_units"]
        if "gas" in limits:
            used = sum(tx.gas_used for tx in included)
            return used < limits["gas"]
        if "bytes" in limits:
            used = sum(tx.size_bytes for tx in included)
            return used < limits["bytes"]

        return False

    def _tx_fits(
        self,
        tx: Transaction,
        included: List[Transaction],
        block_limit: Optional[Dict] = None,
    ) -> bool:
        """Check whether a specific transaction fits in the remaining block space.

        Args:
            tx:          Candidate transaction.
            included:    Transactions already included.
            block_limit: Override block limits.

        Returns:
            True if the transaction fits.
        """
        limits = block_limit or self.BLOCK_LIMITS.get(self.chain, {"bytes": 6_291_456})

        if "weight_units" in limits:
            used = sum(t.weight_units or t.size_bytes for t in included)
            return (used + (tx.weight_units or tx.size_bytes)) <= limits["weight_units"]
        if "gas" in limits:
            used = sum(t.gas_used for t in included)
            return (used + tx.gas_used) <= limits["gas"]
        if "bytes" in limits:
            used = sum(t.size_bytes for t in included)
            return (used + tx.size_bytes) <= limits["bytes"]
        if "compute_units" in limits:
            used = sum(t.compute_units for t in included)
            return (used + tx.compute_units) <= limits["compute_units"]

        return True

    def build_block(
        self,
        mempool: List[Transaction],
        block_limit: Optional[Dict] = None,
    ) -> List[Transaction]:
        """Greedily select transactions by priority score until block is full.

        Args:
            mempool:     List of pending transactions.
            block_limit: Override block capacity limits.

        Returns:
            List of selected transactions (in inclusion order).
        """
        # Score all transactions; use negative score for max-heap via heapq
        scored = [(-self.score_transaction(tx), i, tx) for i, tx in enumerate(mempool)]
        heapq.heapify(scored)

        included: List[Transaction] = []

        while scored:
            neg_score, _, tx = heapq.heappop(scored)
            if self._tx_fits(tx, included, block_limit):
                included.append(tx)
            if not self._capacity_remaining(included, block_limit):
                break

        return included

    def algo_inclusion_bias(
        self,
        mempool: List[Transaction],
        block_limit: Optional[Dict] = None,
    ) -> Dict[str, float]:
        """Compute differential inclusion rates by signature algorithm.

        Reveals whether the block builder systematically favours or disfavours
        certain PQC algorithms at equal absolute fee levels.

        Args:
            mempool:     Pending transactions.
            block_limit: Override block capacity limits.

        Returns:
            Dict mapping algorithm → inclusion_rate (fraction of that algorithm's
            transactions that were selected into the block).
        """
        included = self.build_block(mempool, block_limit)
        included_ids = {tx.tx_id for tx in included}

        # Count by algorithm
        algo_total: Dict[str, int]   = {}
        algo_included: Dict[str, int] = {}

        for tx in mempool:
            algo_total[tx.sig_algorithm] = algo_total.get(tx.sig_algorithm, 0) + 1
            if tx.tx_id in included_ids:
                algo_included[tx.sig_algorithm] = (
                    algo_included.get(tx.sig_algorithm, 0) + 1
                )

        return {
            algo: algo_included.get(algo, 0) / total
            for algo, total in algo_total.items()
        }

    def censorship_threshold(
        self,
        algorithms: Optional[List[str]] = None,
        baseline_fee: float = 1.0,
    ) -> Dict[str, float]:
        """Fee premium multiplier needed to match ECDSA priority score.

        For each PQC algorithm, computes the minimum fee premium a user must
        pay to achieve the same block-builder priority score as a classical
        ECDSA/Ed25519 transaction at the current baseline fee.

        This is the "censorship incentive" metric: how much more expensive
        PQC is for users, purely due to economic validator selection pressure.

        Args:
            algorithms:   Algorithms to compare. Defaults to common PQC set.
            baseline_fee: Baseline fee for the reference classical transaction.

        Returns:
            Dict mapping algorithm → fee_premium_multiplier (1.0 = no premium).
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        if algorithms is None:
            algorithms = [
                "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
                "Falcon-512", "Falcon-1024",
                "SLH-DSA-128s", "SLH-DSA-128f",
            ]

        # Build a reference classical transaction
        def make_tx(algo: str, fee: float) -> Transaction:
            sig_sz = SIGNATURE_SIZES.get(algo, 64)
            pk_sz  = PUBLIC_KEY_SIZES.get(algo, 32)
            tx_sz  = 120 + sig_sz + pk_sz   # simple Ethereum-style tx

            gas   = _eth_gas(algo) if self.chain == "ethereum" else 0
            cu    = _solana_cu(algo) if self.chain == "solana" else 0
            wt    = tx_sz * 4 if self.chain == "bitcoin" else 0  # rough WU

            vtime = VERIFY_TIME_US.get(algo, 60.0)

            return Transaction(
                tx_id         = f"{algo}_{fee}",
                sig_algorithm = algo,
                fee           = fee,
                size_bytes    = tx_sz,
                weight_units  = wt,
                gas_used      = gas,
                compute_units = cu,
                verify_time_us= vtime,
            )

        classical_tx    = make_tx(self.classical_algo, baseline_fee)
        classical_score = self.score_transaction(classical_tx)

        thresholds: Dict[str, float] = {}

        for algo in algorithms:
            pqc_tx_unit = make_tx(algo, 1.0)  # fee=1 to get normalised score
            unit_score  = self.score_transaction(pqc_tx_unit)

            if unit_score > 0:
                # fee needed = classical_score / unit_score_per_fee_unit
                required_fee      = classical_score / unit_score
                thresholds[algo]  = required_fee / baseline_fee
            else:
                thresholds[algo] = float("inf")

        return thresholds

    def inclusion_rate_comparison(
        self,
        algorithms: Optional[List[str]] = None,
        pool_size_per_algo: int = 100,
        baseline_fee: float = 1.0,
    ) -> Dict[str, Dict]:
        """Simulate a mixed mempool and report inclusion rates per algorithm.

        Generates equal numbers of transactions for each algorithm at equal
        fees, then runs the block builder to show which algorithms are
        preferentially excluded.

        Args:
            algorithms:         Algorithms to include in the test.
            pool_size_per_algo: Transactions per algorithm.
            baseline_fee:       Absolute fee each transaction pays.

        Returns:
            Dict mapping algorithm → {inclusion_rate, avg_score, fee_premium_needed}.
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        if algorithms is None:
            algorithms = [
                self.classical_algo,
                "ML-DSA-65", "Falcon-512", "SLH-DSA-128s", "SLH-DSA-128f",
            ]

        mempool: List[Transaction] = []
        for algo in algorithms:
            for j in range(pool_size_per_algo):
                sig_sz = SIGNATURE_SIZES.get(algo, 64)
                pk_sz  = PUBLIC_KEY_SIZES.get(algo, 32)
                tx_sz  = 120 + sig_sz + pk_sz

                mempool.append(Transaction(
                    tx_id         = f"{algo}_{j}",
                    sig_algorithm = algo,
                    fee           = baseline_fee,
                    size_bytes    = tx_sz,
                    gas_used      = _eth_gas(algo) if self.chain == "ethereum" else 0,
                    compute_units = _solana_cu(algo) if self.chain == "solana" else 0,
                    weight_units  = tx_sz * 4 if self.chain == "bitcoin" else 0,
                ))

        inclusion_rates = self.algo_inclusion_bias(mempool)
        thresholds      = self.censorship_threshold(algorithms, baseline_fee)

        result = {}
        for algo in algorithms:
            algo_txs = [tx for tx in mempool if tx.sig_algorithm == algo]
            avg_score = (
                sum(self.score_transaction(t) for t in algo_txs) / len(algo_txs)
                if algo_txs else 0.0
            )
            result[algo] = {
                "inclusion_rate":       inclusion_rates.get(algo, 0.0),
                "avg_score":            avg_score,
                "fee_premium_needed":   thresholds.get(algo, float("inf")),
            }

        return result
