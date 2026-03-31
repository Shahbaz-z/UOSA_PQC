"""Phase 2/3 DES Engine: Stochastic PQC Shock + Economic Mempool Eviction.

RELATIONSHIP TO DESEngine
─────────────────────────
Phase2Engine WRAPS DESEngine via composition (not inheritance).
Do NOT replace DESEngine with Phase2Engine — they serve different purposes.
See simulator/core/engine.py for the full engine hierarchy diagram.

  Phase2Engine.__init__() constructs a DESEngine internally and stores
  it as self._engine.  At runtime, Phase2Engine.run() monkey-patches
  two of DESEngine's event handlers:

    _create_block          → self._create_heterogeneous_block
    _handle_block_received → patched_handle_received (per-tx verify)

  After patching, it calls self._engine.run() to execute the event loop,
  then computes extended Phase 2/3 metrics from the result.

ADDED CAPABILITIES (beyond Phase 1 DESEngine)
──────────────────────────────────────────────
  1. PoissonArrivalModel — stochastic transaction generation
  2. GlobalMempool       — bounded 100 MB capacity, fee-rate eviction
  3. AlgorithmMix        — heterogeneous classical + PQC signature blocks
  4. Per-transaction verification — CPU resources locked per sig algorithm
  5. DynamicFeeMarket    — EIP-1559/first-price/priority-fee models
  6. Vote transactions   — Solana-specific block-space overhead injection

CRITICAL PHYSICS CONSTRAINT
────────────────────────────
  When verifying a heterogeneous block, each transaction is iterated
  individually. The CPU core is occupied for the EXACT verification time
  of that transaction's specific signature algorithm.
  This means an SLH-DSA-128f signature (5,940 µs) physically blocks
  a CPU core 100× longer than an Ed25519 signature (60 µs).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import simpy

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.core.events import EventType, Event
from simulator.state import SimulationState
from simulator.results import SimulationResult
from simulator.network.node import Node
from simulator.network.propagation import Block, Transaction
from simulator.mempool import PoissonArrivalModel
from simulator.mempool.mempool import GlobalMempool
from simulator.mempool.algorithm_mix import AlgorithmMixGenerator, AlgorithmMixConfig
from simulator.economics.fee_market import (
    DynamicFeeMarket,
    FeeMarketConfig,
    FEE_MARKET_PRESETS,
)
from simulator.chains.bitcoin_specific import DEFAULT_BITCOIN_TX_MODEL
from simulator.chains.ethereum_specific import DEFAULT_ETHEREUM_TX_MODEL
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
from blockchain.verification import VERIFICATION_PROFILES

logger = logging.getLogger(__name__)


@dataclass
class Phase2Config:
    """Configuration for Phase 2/3 extensions on top of SimulationConfig.

    Attributes:
        pqc_fraction: Fraction of transactions using PQC [0.0, 1.0].
        lambda_tps: Poisson arrival rate (transactions per second).
        mempool_capacity_bytes: Bounded mempool size in bytes.
        pqc_weights: Relative weights for PQC algorithm sub-selection.
        classical_algo: Classical baseline signature algorithm.
    """
    chain: str
    pqc_fraction: float = 0.0
    lambda_tps: float = 500.0
    mempool_capacity_bytes: int = 100 * 1024 * 1024  # 100 MB
    classical_algo: str = "Ed25519"
    pqc_weights: Optional[Dict[str, float]] = None

    # Simulation parameters
    num_validators: int = 50
    num_full_nodes: int = 25
    simulation_duration_ms: float = 60_000  # 1 minute
    random_seed: int = 42

    # Override chain block time / size if desired
    block_time_ms: Optional[float] = None
    block_size_limit_bytes: Optional[int] = None

    # Realism flags (Phase B upgrades)
    nic_contention_enabled: bool = True
    use_chain_routing: bool = True

    # Phase G: Fee market
    fee_market_enabled: bool = False
    fee_market_config: Optional[FeeMarketConfig] = None  # None = use chain preset

    # Phase G: Vote transaction overhead (Solana-specific)
    vote_tx_fraction: float = 0.0  # Fraction of block space reserved for votes


class Phase2Engine:
    """Phase 2/3 Simulation Engine with heterogeneous PQC transactions.

    Extends the Phase 1 propagation engine with:
    - Poisson transaction arrivals filling a bounded mempool
    - Fee-rate-based eviction under mempool pressure
    - Heterogeneous signature blocks (mixed classical + PQC)
    - Per-transaction verification with CPU resource locking

    The core event loop remains the same (SLOT_TICK → BLOCK_PROPOSED →
    BLOCK_PROPAGATED → BLOCK_RECEIVED → BLOCK_VALIDATED), but block
    creation now pulls from the mempool and verification iterates
    each transaction individually.
    """

    def __init__(self, config: Phase2Config) -> None:
        self.config = config
        self.rng = random.Random(config.random_seed)

        # Build SimulationConfig for the underlying Phase 1 engine
        self._sim_config = SimulationConfig(
            chain=config.chain,
            signature_algorithm=config.classical_algo,
            num_validators=config.num_validators,
            num_full_nodes=config.num_full_nodes,
            simulation_duration_ms=config.simulation_duration_ms,
            random_seed=config.random_seed,
            block_time_ms=config.block_time_ms,
            block_size_limit_bytes=config.block_size_limit_bytes,
            nic_contention_enabled=config.nic_contention_enabled,
            use_chain_routing=config.use_chain_routing,
        )

        # Construct the Phase 1 engine (network, topology, state)
        self._engine = DESEngine(self._sim_config)

        # Phase 2 components
        self._arrival_model = PoissonArrivalModel(
            lambda_tps=config.lambda_tps,
            rng=random.Random(config.random_seed + 1),
        )

        self._mempool = GlobalMempool(
            capacity_bytes=config.mempool_capacity_bytes,
        )

        mix_config = AlgorithmMixConfig(
            pqc_fraction=config.pqc_fraction,
            classical_algo=config.classical_algo,
            pqc_weights=config.pqc_weights,
        )
        self._algo_mix = AlgorithmMixGenerator(
            config=mix_config,
            rng=random.Random(config.random_seed + 2),
        )

        # Phase G: Fee market
        self._fee_market: Optional[DynamicFeeMarket] = None
        if config.fee_market_enabled:
            fm_config = config.fee_market_config or FEE_MARKET_PRESETS.get(
                config.chain, FeeMarketConfig()
            )
            self._fee_market = DynamicFeeMarket(
                fm_config, rng=random.Random(config.random_seed + 3)
            )

        # Phase G: Vote tracking
        self._vote_txs_generated: int = 0
        self._vote_bytes_total: int = 0

        # Slot time tracking for accurate inter-slot interval calculation.
        # IMPORTANT: patched_handle_slot must use the ACTUAL elapsed interval
        # (current_time - last_slot_time), NOT the nominal block_time_ms constant.
        # Using the nominal constant systematically overcounts transactions when
        # actual slot intervals are longer than block_time_ms (e.g. due to
        # propagation delays and queued events shifting slot boundaries).
        self._last_slot_time_ms: float = 0.0

        # Metrics accumulators
        self._blocks_produced: List[Block] = []
        self._total_evictions: int = 0
        self._total_tx_generated: int = 0
        self._economic_rejections: int = 0
        self._verification_times_ms: List[float] = []

    def run(self) -> Dict:
        """Execute the Phase 2/3 simulation.

        Returns:
            Dictionary with comprehensive simulation results including
            propagation, verification, mempool, and failure metrics.
        """
        # Pre-fill mempool with transactions arriving before the first block.
        # Set _last_slot_time_ms to 0.0 so the first patched_handle_slot computes
        # the actual elapsed interval correctly rather than double-counting.
        self._last_slot_time_ms = 0.0
        self._generate_transactions_until(self._engine.block_time_ms)

        # Run the event loop with Phase 2 overrides
        self._engine._create_block = self._create_heterogeneous_block  # type: ignore

        # Monkey-patch the block verification to use per-tx iteration
        original_handle_received = self._engine._handle_block_received

        def patched_handle_received(event: Event) -> None:
            """Override: use per-transaction verification times."""
            block_hash = event.payload["block_hash"]
            receiver_id = event.payload["receiver_id"]
            receiver = self._engine.topology.get_node(receiver_id)

            block = self._engine.state.get_block_by_hash(block_hash)
            if not block or receiver.has_seen_block(block_hash):
                return

            block.first_seen_by[receiver_id] = self._engine.state.current_time_ms
            receiver.mark_block_seen(block_hash, self._engine.state.current_time_ms)

            # CRITICAL: Per-transaction heterogeneous verification
            verify_time = self._compute_heterogeneous_verify_time(
                block, receiver
            )

            # Use CPU scheduling queue: if all cores are busy, queuing adds delay
            completion_time_ms = receiver.schedule_verification(
                arrival_time_ms=self._engine.state.current_time_ms,
                verify_duration_ms=verify_time,
            )

            self._engine.state.schedule_event(
                time_ms=completion_time_ms,
                event_type=EventType.BLOCK_VALIDATED,
                payload={
                    "block_hash": block_hash,
                    "validator_id": receiver_id,
                },
            )

        self._engine._handle_block_received = patched_handle_received  # type: ignore
        self._engine._handlers[EventType.BLOCK_RECEIVED] = patched_handle_received

        # Patch SLOT_TICK to also generate transactions between blocks
        original_handle_slot = self._engine._handle_slot_tick

        def patched_handle_slot(event: Event) -> None:
            # Compute the ACTUAL elapsed time since the previous slot tick.
            # Using the nominal block_time_ms constant here would be incorrect:
            # in a stochastic DES the time between slot events can exceed the
            # nominal block time (e.g. due to propagation delays, queued events,
            # or sub-ms floating-point rounding in the heapq scheduler).
            # Passing the nominal constant causes the mempool to be refilled
            # with a full interval's worth of transactions every slot even when
            # less time has actually elapsed, systematically overcounting
            # total_tx_generated and inflating eviction rates.
            current_time = self._engine.state.current_time_ms
            actual_interval_ms = max(
                0.0, current_time - self._last_slot_time_ms
            )
            # Fall back to nominal interval on the very first slot (where
            # last_slot_time_ms == 0.0 and current_time == 0.0)
            if actual_interval_ms == 0.0:
                actual_interval_ms = self._engine.block_time_ms
            self._last_slot_time_ms = current_time

            self._generate_transactions_until(actual_interval_ms)

            # Phase G: Update fee market after each block
            if self._fee_market is not None:
                mempool_util = self._mempool.utilization
                block_util = 1.0  # Assume full blocks for now
                self._fee_market.update_base_fee(
                    current_time_ms=current_time,
                    mempool_utilization=mempool_util,
                    block_utilization=block_util,
                )
            original_handle_slot(event)

        self._engine._handle_slot_tick = patched_handle_slot  # type: ignore
        self._engine._handlers[EventType.SLOT_TICK] = patched_handle_slot

        # Run the engine
        result = self._engine.run()

        # Compute Phase 2/3 extended metrics
        return self._compute_phase2_results(result)

    def _generate_transactions_until(self, interval_ms: float) -> None:
        """Generate Poisson-arriving transactions for the given interval.

        Fills the mempool with transactions, each with a randomly sampled
        signature algorithm according to the AlgorithmMix distribution.

        Transaction sizes use chain-specific models (Phase G) for accurate
        byte sizing. Fee market integration assigns realistic fees and
        tracks economic failures.

        Phase G additions:
        - Dynamic fee market: fee assignment and economic rejection
        - Vote transaction injection (Solana-specific)
        """
        elapsed_ms = 0.0
        chain = self.config.chain.lower()

        while elapsed_ms < interval_ms:
            inter_arrival = self._arrival_model.next_inter_arrival_ms()
            elapsed_ms += inter_arrival
            if elapsed_ms >= interval_ms:
                break

            # Sample algorithm for this transaction
            algo = self._algo_mix.sample()
            is_pqc = algo not in ("Ed25519", "ECDSA")

            # Chain-specific byte sizing for propagation
            sig_size = SIGNATURE_SIZES.get(algo, 64)
            pk_size = PUBLIC_KEY_SIZES.get(algo, 32)

            if chain == "bitcoin":
                tx_size = DEFAULT_BITCOIN_TX_MODEL.tx_bytes(sig_size, pk_size)
            elif chain == "ethereum":
                tx_size = DEFAULT_ETHEREUM_TX_MODEL.tx_bytes(sig_size, pk_size)
            else:
                prop_overhead = self._engine.chain_config.propagation_tx_overhead_bytes
                if prop_overhead == 0:
                    prop_overhead = self._engine.chain_config.base_tx_overhead
                tx_size = self._algo_mix.tx_size_bytes(algo, prop_overhead)

            # Fee assignment: use fee market if enabled
            if self._fee_market is not None:
                fee = self._fee_market.generate_tx_fee(tx_size, is_pqc=is_pqc)
            else:
                fee = self.rng.randint(100, 50_000)

            tx = Transaction(
                tx_id=f"tx_{self._total_tx_generated}",
                size_bytes=tx_size,
                signature_algorithm=algo,
                num_signatures=1,
                fee_satoshis=fee,
                arrival_time_ms=self._engine.state.current_time_ms + elapsed_ms,
            )

            # Economic failure check
            if self._fee_market is not None:
                if not self._fee_market.check_acceptable(fee, tx_size):
                    self._economic_rejections += 1
                    self._total_tx_generated += 1
                    continue  # Transaction rejected — economic failure

            accepted, evicted = self._mempool.add_transaction(tx)
            self._total_evictions += len(evicted)
            self._total_tx_generated += 1

        # Phase G: Inject vote transactions (Solana only)
        if chain == "solana" and self.config.vote_tx_fraction > 0:
            self._inject_vote_transactions(interval_ms)

    def _inject_vote_transactions(self, interval_ms: float) -> None:
        """Inject vote transactions into the mempool (Solana-specific).

        Solana validators submit vote transactions every slot (~400ms).
        These consume block space and bandwidth but always use Ed25519
        (system program doesn't change during PQC transition).

        Vote transactions:
        - Size: ~1,232 bytes (compressed Solana vote)
        - Algorithm: Ed25519 (always classical)
        - Priority: Very high (must be included)
        """
        VOTE_TX_SIZE = 1232  # Compressed vote tx
        VOTE_FEE = 100_000  # High priority — votes must be included

        # Number of vote txs per interval = num_validators * fraction
        num_votes = int(self.config.num_validators * self.config.vote_tx_fraction)

        for i in range(num_votes):
            tx = Transaction(
                tx_id=f"vote_{self._vote_txs_generated}",
                size_bytes=VOTE_TX_SIZE,
                signature_algorithm="Ed25519",  # Votes always use classical sigs
                num_signatures=1,
                fee_satoshis=VOTE_FEE,
                arrival_time_ms=self._engine.state.current_time_ms,
            )
            accepted, evicted = self._mempool.add_transaction(tx)
            self._total_evictions += len(evicted)
            self._vote_txs_generated += 1
            self._vote_bytes_total += VOTE_TX_SIZE

    def _create_heterogeneous_block(self, proposer: Node) -> Block:
        """Create a block from mempool with heterogeneous signatures.

        Pulls the highest-fee-rate transactions from the mempool up to
        the block size limit. Uses chain-specific capacity models.

        Phase G: Bitcoin uses weight units, Ethereum uses gas.
        """
        chain = self.config.chain.lower()
        max_block_size = self._engine.block_size_limit

        # For mempool selection we use byte size (propagation size)
        # The capacity constraint is chain-specific but mempool stores byte-sized txs
        max_txs = max_block_size  # effectively unlimited; byte budget is the real constraint

        # Select transactions from mempool
        candidates = self._mempool.get_block_candidates(
            max_block_size_bytes=max_block_size,
            max_txs=max_txs,
        )

        # Remove selected transactions from mempool
        for tx in candidates:
            self._mempool.remove_transaction(tx.tx_id)

        # If mempool is empty, create a minimal block
        if not candidates:
            # Generate at least one transaction
            algo = self._algo_mix.sample()
            base_overhead = self._engine.chain_config.base_tx_overhead
            tx_size = self._algo_mix.tx_size_bytes(algo, base_overhead)
            candidates = [
                Transaction(
                    tx_id=f"tx_filler_{self._engine.state.chain_height + 1}",
                    size_bytes=tx_size,
                    signature_algorithm=algo,
                    num_signatures=1,
                    fee_satoshis=self.rng.randint(100, 10_000),
                    arrival_time_ms=self._engine.state.current_time_ms,
                )
            ]

        # Determine the "primary" signature algorithm for the block
        # (most common algorithm in the block, for metadata)
        algo_counts: Dict[str, int] = {}
        for tx in candidates:
            algo_counts[tx.signature_algorithm] = algo_counts.get(
                tx.signature_algorithm, 0
            ) + 1
        primary_algo = max(algo_counts, key=algo_counts.get)  # type: ignore

        block = Block(
            block_hash=f"block_{self._engine.state.chain_height + 1}",
            parent_hash=self._engine.state.chain_tip_hash,
            height=self._engine.state.chain_height + 1,
            proposer_id=proposer.node_id,
            timestamp_ms=self._engine.state.current_time_ms,
            transactions=candidates,
            signature_algorithm=primary_algo,
        )

        self._blocks_produced.append(block)
        return block

    def _compute_heterogeneous_verify_time(
        self, block: Block, node: Node
    ) -> float:
        """Compute verification time iterating each transaction individually.

        CRITICAL PHYSICS CONSTRAINT:
        Each transaction's signature is verified sequentially on a per-core
        basis. The total time is the sum of individual verification times
        divided by the node's CPU cores (parallel verification across cores).

        For a heterogeneous block:
          total_serial_us = Σ verify_time_us(tx.signature_algorithm)
          total_parallel_ms = total_serial_us / (cpu_cores × processing_factor × 1000)
        """
        total_serial_us = 0.0

        for tx in block.transactions:
            profile = VERIFICATION_PROFILES.get(tx.signature_algorithm)
            if profile:
                total_serial_us += profile.verify_time_us * tx.num_signatures
            else:
                # Unknown algo: conservative 500 µs/sig
                total_serial_us += 500.0 * tx.num_signatures

        # Parallelize across CPU cores, adjusted for processing power
        effective_cores = (
            node.config.cpu_cores * node.config.processing_power_factor
        )
        if effective_cores <= 0:
            effective_cores = 1.0

        total_parallel_us = total_serial_us / effective_cores
        total_ms = total_parallel_us / 1000.0

        self._verification_times_ms.append(total_ms)
        return total_ms

    def _compute_phase2_results(self, base_result: SimulationResult) -> Dict:
        """Compute extended Phase 2/3 results.

        Returns:
            Dictionary with all Phase 1 metrics plus Phase 2/3 additions.
        """
        mempool_stats = self._mempool.stats()

        # Compute per-block algorithm distribution
        algo_distribution: Dict[str, int] = {}
        total_block_txs = 0
        for block in self._blocks_produced:
            for tx in block.transactions:
                algo_distribution[tx.signature_algorithm] = (
                    algo_distribution.get(tx.signature_algorithm, 0) + 1
                )
                total_block_txs += 1

        algo_fractions = {
            algo: count / total_block_txs if total_block_txs > 0 else 0.0
            for algo, count in algo_distribution.items()
        }

        # Average verification time
        avg_verify_ms = (
            sum(self._verification_times_ms) / len(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )
        max_verify_ms = (
            max(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )

        # Network failure detection
        # A block "fails" if verification time exceeds the block interval
        block_time_ms = self._engine.block_time_ms
        verification_failures = sum(
            1 for v in self._verification_times_ms if v > block_time_ms
        )
        verification_failure_rate = (
            verification_failures / len(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )

        # Stale rate: blocks where p90 propagation > 90% of block time
        stale_threshold = block_time_ms * 0.9

        return {
            # Phase 1 metrics (from base result)
            "chain": base_result.chain,
            "pqc_fraction": self.config.pqc_fraction,
            "seed": self.config.random_seed,
            "num_blocks": base_result.num_blocks,
            "avg_block_size_bytes": base_result.avg_block_size_bytes,
            "avg_txs_per_block": base_result.avg_txs_per_block,
            "avg_propagation_p50_ms": base_result.avg_propagation_p50_ms,
            "avg_propagation_p90_ms": base_result.avg_propagation_p90_ms,
            "avg_propagation_p95_ms": base_result.avg_propagation_p95_ms,
            "stale_rate": base_result.stale_rate,
            "effective_tps": base_result.effective_tps,

            # Phase 2: Verification metrics
            "avg_verification_time_ms": round(avg_verify_ms, 4),
            "max_verification_time_ms": round(max_verify_ms, 4),
            "verification_failure_rate": round(verification_failure_rate, 6),
            "verification_failures": verification_failures,
            "block_time_ms": block_time_ms,

            # Phase 3: Mempool metrics
            "mempool_total_accepted": mempool_stats.total_accepted,
            "mempool_total_evicted": mempool_stats.total_evicted,
            "mempool_total_rejected": mempool_stats.total_rejected,
            "mempool_final_size_bytes": mempool_stats.current_size_bytes,
            "mempool_final_tx_count": mempool_stats.current_tx_count,
            "total_tx_generated": self._total_tx_generated,

            # Algorithm distribution in blocks
            "algo_distribution": algo_fractions,
            "algo_counts": algo_distribution,

            # Phase G: Fee market metrics
            **self._compute_fee_market_metrics(),

            # Phase G: Vote overhead metrics
            **self._compute_vote_metrics(),
        }

    def _compute_fee_market_metrics(self) -> Dict:
        """Compute fee market metrics for results."""
        if self._fee_market is None:
            return {
                "fee_market_enabled": False,
                "economic_failure_count": 0,
                "economic_failure_rate": 0.0,
            }

        fm_metrics = self._fee_market.metrics()
        fm_metrics["economic_failure_count"] = self._economic_rejections
        fm_metrics["economic_failure_rate"] = (
            self._economic_rejections / self._total_tx_generated
            if self._total_tx_generated > 0
            else 0.0
        )
        return fm_metrics

    def _compute_vote_metrics(self) -> Dict:
        """Compute vote transaction overhead metrics."""
        num_blocks = len(self._blocks_produced)
        if num_blocks == 0:
            return {
                "vote_tx_fraction_config": self.config.vote_tx_fraction,
                "vote_tx_count_total": 0,
                "vote_tx_count_per_block": 0.0,
                "vote_overhead_bytes_total": 0,
                "vote_overhead_bytes_per_block": 0.0,
                "vote_overhead_fraction": 0.0,
                "effective_user_tps": 0.0,
            }

        # Count vote txs in produced blocks
        vote_txs_in_blocks = 0
        vote_bytes_in_blocks = 0
        user_txs_in_blocks = 0
        for block in self._blocks_produced:
            for tx in block.transactions:
                if tx.tx_id.startswith("vote_"):
                    vote_txs_in_blocks += 1
                    vote_bytes_in_blocks += tx.size_bytes
                else:
                    user_txs_in_blocks += 1

        total_block_bytes = sum(b.size_bytes for b in self._blocks_produced)
        sim_duration_s = self.config.simulation_duration_ms / 1000.0

        return {
            "vote_tx_fraction_config": self.config.vote_tx_fraction,
            "vote_tx_count_total": vote_txs_in_blocks,
            "vote_tx_count_per_block": round(vote_txs_in_blocks / num_blocks, 2),
            "vote_overhead_bytes_total": vote_bytes_in_blocks,
            "vote_overhead_bytes_per_block": round(vote_bytes_in_blocks / num_blocks, 2),
            "vote_overhead_fraction": (
                round(vote_bytes_in_blocks / total_block_bytes, 4)
                if total_block_bytes > 0
                else 0.0
            ),
            "effective_user_tps": (
                round(user_txs_in_blocks / sim_duration_s, 2)
                if sim_duration_s > 0
                else 0.0
            ),
        }
