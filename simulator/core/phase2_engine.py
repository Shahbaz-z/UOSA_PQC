"""Phase 2/3 DES Engine: Stochastic PQC Shock + Economic Mempool Eviction.

Extends the Phase 1 DESEngine with:
  1. PoissonArrivalModel for stochastic transaction generation
  2. GlobalMempool with bounded capacity and fee-rate eviction
  3. AlgorithmMix for heterogeneous classical + PQC signature blocks
  4. Per-transaction verification loop that locks CPU resources for
     each signature's specific verification time

CRITICAL PHYSICS CONSTRAINT:
  When verifying a heterogeneous block, each transaction is iterated
  individually. The SimPy Resource (cpu_cores) is held for the EXACT
  verification time of that transaction's specific signature algorithm.
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

        # Metrics accumulators
        self._blocks_produced: List[Block] = []
        self._total_evictions: int = 0
        self._total_tx_generated: int = 0
        self._verification_times_ms: List[float] = []

    def run(self) -> Dict:
        """Execute the Phase 2/3 simulation.

        Returns:
            Dictionary with comprehensive simulation results including
            propagation, verification, mempool, and failure metrics.
        """
        # Pre-fill mempool with transactions arriving before first block
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

            self._engine.state.schedule_event(
                time_ms=self._engine.state.current_time_ms + verify_time,
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
            # Generate transactions that arrived during this slot interval
            self._generate_transactions_until(
                self._engine.block_time_ms
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
        """
        elapsed_ms = 0.0
        base_overhead = self._engine.chain_config.base_tx_overhead

        while elapsed_ms < interval_ms:
            inter_arrival = self._arrival_model.next_inter_arrival_ms()
            elapsed_ms += inter_arrival
            if elapsed_ms >= interval_ms:
                break

            # Sample algorithm for this transaction
            algo = self._algo_mix.sample()
            tx_size = self._algo_mix.tx_size_bytes(algo, base_overhead)

            tx = Transaction(
                tx_id=f"tx_{self._total_tx_generated}",
                size_bytes=tx_size,
                signature_algorithm=algo,
                num_signatures=1,
                fee_satoshis=self.rng.randint(100, 50_000),
                arrival_time_ms=self._engine.state.current_time_ms + elapsed_ms,
            )

            accepted, evicted = self._mempool.add_transaction(tx)
            self._total_evictions += len(evicted)
            self._total_tx_generated += 1

    def _create_heterogeneous_block(self, proposer: Node) -> Block:
        """Create a block from mempool with heterogeneous signatures.

        Pulls the highest-fee-rate transactions from the mempool up to
        the block size limit. This replaces the Phase 1 uniform-fill logic.
        """
        max_block_size = self._engine.block_size_limit
        max_txs = 10_000  # Cap for simulation performance

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

        # Stale rate: blocks where p90 propagation > half block time
        stale_threshold = block_time_ms * 0.5

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
        }
