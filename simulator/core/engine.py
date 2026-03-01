"""Discrete Event Simulation engine for blockchain network propagation.

DESIGN NOTES:

1. BANDWIDTH MODEL:
   - Propagation delay is computed analytically from block size, link bandwidth,
     and inter-node latency.  Full NIC-level contention is NOT modelled (each
     gossip transmission is treated independently).  This is a known
     simplification documented in ASSUMPTIONS_AND_LIMITATIONS.md.

2. CPU CONTENTION:
   - Verification times are scheduled on a per-core analytical heap:
     each node tracks when each CPU core becomes free (`_core_free_at`).
   - Heavy PQC signatures (SLH-DSA: 6–15 ms) physically delay verification
     of subsequent blocks, creating realistic node saturation under PQC load.

3. EVENT LOOP:
   - Uses a bespoke heapq-based priority queue for event scheduling.
     (Originally prototyped with SimPy; replaced with an analytical min-heap
     scheduler for performance and determinism.)
   - Time advances discretely between events.
   - All randomness is seeded for reproducibility.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

from simulator.core.events import EventType, Event
from simulator.state import SimulationState
from simulator.results import SimulationResult
from simulator.network.node import Node, NodeConfig
from simulator.network.topology import NetworkTopology, REGIONS
from simulator.network.propagation import Block, Transaction
from simulator.chains.base import get_chain_config, ChainConfig
from simulator.models.bandwidth import (
    sample_validator_config,
    sample_full_node_config,
    region_distribution,
)

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    """Configuration for a simulation run."""

    chain: str                          # "solana", "bitcoin", "ethereum"
    signature_algorithm: str            # "Ed25519", "ML-DSA-65", etc.
    num_validators: int = 200           # Number of validator nodes
    num_full_nodes: int = 100           # Number of non-validator full nodes
    simulation_duration_ms: float = 300_000  # 5 minutes default
    random_seed: int = 42

    # Chain parameters (if None, uses chain defaults)
    block_time_ms: Optional[float] = None
    block_size_limit_bytes: Optional[int] = None

    # Gossip parameters
    gossip_fanout: int = 0  # 0 = use chain config default


class DESEngine:
    """Discrete Event Simulation engine for network propagation modeling.

    Models block proposal, propagation, and validation across a network
    of heterogeneous nodes with realistic bandwidth and CPU constraints.

    The simulation proceeds through discrete events:
    1. SLOT_TICK: Time boundary, select block proposer
    2. BLOCK_PROPOSED: Proposer creates and broadcasts block
    3. BLOCK_PROPAGATED: Node forwards block to gossip peers
    4. BLOCK_RECEIVED: Node receives block, queues for validation
    5. BLOCK_VALIDATED: Node validates block, forwards to peers

    Resource contention is modeled analytically:
    - Bandwidth: propagation delay computed from block size / link speed
    - CPU: verification scheduled on a per-core heap (_core_free_at)
    """

    def __init__(self, config: SimulationConfig):
        """Initialize simulation engine.

        Args:
            config: Simulation configuration.
        """
        self.config = config
        self.rng = random.Random(config.random_seed)

        # Simulation clock (pure analytical; no SimPy dependency)
        self._clock_ms: float = 0.0

        # Load chain configuration
        self.chain_config = get_chain_config(config.chain)

        # Override chain params if specified
        self.block_time_ms = config.block_time_ms or self.chain_config.block_time_ms
        self.block_size_limit = (
            config.block_size_limit_bytes or self.chain_config.block_size_limit
        )
        self.gossip_fanout = config.gossip_fanout if config.gossip_fanout else self.chain_config.gossip_fanout

        # Network components
        self.topology = NetworkTopology(rng=self.rng)
        self.state = SimulationState(end_time_ms=config.simulation_duration_ms)

        # Event handlers
        self._handlers: Dict[EventType, Callable[[Event], None]] = {
            EventType.SLOT_TICK: self._handle_slot_tick,
            EventType.BLOCK_PROPOSED: self._handle_block_proposed,
            EventType.BLOCK_PROPAGATED: self._handle_block_propagated,
            EventType.BLOCK_RECEIVED: self._handle_block_received,
            EventType.BLOCK_VALIDATED: self._handle_block_validated,
        }

        # Initialize network
        self._setup_network()

    def _setup_network(self) -> None:
        """Create nodes with realistic geographic and hardware distribution."""
        regions = list(REGIONS.keys())
        region_weights = region_distribution()
        region_list = list(region_weights.keys())
        weights = list(region_weights.values())

        # Create validators
        for i in range(self.config.num_validators):
            region = self.rng.choices(region_list, weights=weights)[0]
            node_config = sample_validator_config(
                node_id=f"validator_{i}",
                region=region,
                rng=self.rng,
                is_validator=True,
            )
            node = Node(node_config, env=None)
            self.topology.add_node(node)

        # Create full nodes
        for i in range(self.config.num_full_nodes):
            region = self.rng.choices(region_list, weights=weights)[0]
            node_config = sample_full_node_config(
                node_id=f"fullnode_{i}",
                region=region,
                rng=self.rng,
            )
            node = Node(node_config, env=None)
            self.topology.add_node(node)

        logger.debug(
            f"Network initialized: {self.topology.validator_count()} validators, "
            f"{self.topology.node_count() - self.topology.validator_count()} full nodes"
        )

    def run(self) -> SimulationResult:
        """Execute the simulation and return results.

        Returns:
            SimulationResult with propagation metrics and stale rate.
        """
        logger.info(
            f"Starting simulation: {self.config.chain}, "
            f"{self.config.signature_algorithm}, "
            f"{self.config.simulation_duration_ms}ms"
        )

        # Schedule initial slot tick
        self._schedule_initial_events()

        # Main event loop
        events_processed = 0
        while self.state.has_events():
            event = self.state.pop_next_event()

            if event.time_ms > self.state.end_time_ms:
                break

            self.state.current_time_ms = event.time_ms

            # Dispatch to handler
            handler = self._handlers.get(event.event_type)
            if handler:
                handler(event)

            self.state.completed_events.append(event)
            events_processed += 1

        logger.info(
            f"Simulation complete: {len(self.state.blocks_proposed)} blocks, "
            f"{events_processed} events"
        )

        return self._compute_results()

    def _schedule_initial_events(self) -> None:
        """Schedule the first slot tick."""
        proposer = self._select_proposer()
        self.state.schedule_event(
            time_ms=0.0,
            event_type=EventType.SLOT_TICK,
            payload={"proposer_id": proposer.node_id},
        )

    def _select_proposer(self) -> Node:
        """Select next block proposer (stake-weighted for PoS)."""
        validators = self.topology.get_validators()
        if not validators:
            raise RuntimeError("No validators in network")

        weights = [v.config.stake_weight for v in validators]
        return self.rng.choices(validators, weights=weights)[0]

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    def _handle_slot_tick(self, event: Event) -> None:
        """Handle slot boundary: trigger block proposal."""
        proposer_id = event.payload.get("proposer_id")

        # Schedule block proposal
        self.state.schedule_event(
            time_ms=self.state.current_time_ms,
            event_type=EventType.BLOCK_PROPOSED,
            payload={"proposer_id": proposer_id},
        )

        # Schedule next slot tick
        next_slot_time = self.state.current_time_ms + self.block_time_ms
        if next_slot_time < self.state.end_time_ms:
            next_proposer = self._select_proposer()
            self.state.schedule_event(
                time_ms=next_slot_time,
                event_type=EventType.SLOT_TICK,
                payload={"proposer_id": next_proposer.node_id},
            )

    def _handle_block_proposed(self, event: Event) -> None:
        """Handle block proposal: create block and start propagation."""
        proposer_id = event.payload["proposer_id"]
        proposer = self.topology.get_node(proposer_id)

        # Create block
        block = self._create_block(proposer)
        self.state.register_block(block)

        # Proposer immediately has and validates the block (they built it)
        block.first_seen_by[proposer_id] = self.state.current_time_ms
        block.validated_by[proposer_id] = self.state.current_time_ms
        proposer.mark_block_seen(block.block_hash, self.state.current_time_ms)

        logger.debug(
            f"Block {block.height} proposed by {proposer_id}: "
            f"{block.size_bytes} bytes, {block.tx_count} txs"
        )

        # Schedule propagation to peers
        self.state.schedule_event(
            time_ms=self.state.current_time_ms,
            event_type=EventType.BLOCK_PROPAGATED,
            payload={"block_hash": block.block_hash, "sender_id": proposer_id},
        )

    def _handle_block_propagated(self, event: Event) -> None:
        """Handle block propagation: send to gossip peers.

        CRITICAL: This models bandwidth contention by computing
        transmission time based on block size and bottleneck bandwidth.
        """
        block_hash = event.payload["block_hash"]
        sender_id = event.payload["sender_id"]
        sender = self.topology.get_node(sender_id)

        block = self.state.get_block_by_hash(block_hash)
        if not block:
            return

        # Select peers for gossip (exclude those who already have the block)
        peers = self._select_gossip_peers(sender, block)

        for peer in peers:
            if peer.has_seen_block(block_hash):
                continue

            # Compute propagation delay: geographic latency + transmission time
            # This is where bandwidth contention manifests: larger blocks
            # take longer to transmit, especially over slow links
            delay_ms = self.topology.compute_propagation_delay(
                sender, peer, block.size_bytes
            )

            receive_time = self.state.current_time_ms + delay_ms

            self.state.schedule_event(
                time_ms=receive_time,
                event_type=EventType.BLOCK_RECEIVED,
                payload={
                    "block_hash": block_hash,
                    "receiver_id": peer.node_id,
                    "sender_id": sender_id,
                },
            )

    def _handle_block_received(self, event: Event) -> None:
        """Handle block receipt: queue for validation.

        CRITICAL: This marks the block as seen and schedules validation.
        Verification time depends on signature algorithm and signature count.
        """
        block_hash = event.payload["block_hash"]
        receiver_id = event.payload["receiver_id"]
        receiver = self.topology.get_node(receiver_id)

        block = self.state.get_block_by_hash(block_hash)
        if not block:
            return

        # Skip if already seen
        if receiver.has_seen_block(block_hash):
            return

        # Record first seen time
        block.first_seen_by[receiver_id] = self.state.current_time_ms
        receiver.mark_block_seen(block_hash, self.state.current_time_ms)

        # Schedule validation
        # Verification time is computed based on:
        # 1. Signature algorithm (PQC is slower)
        # 2. Number of signatures in block
        # 3. Node's processing power
        # 4. CPU core availability (analytical queuing model)
        verify_time = receiver.verification_time_ms(
            block.signature_algorithm,
            block.total_signatures,
        )

        # Use CPU scheduling queue: if all cores are busy, queuing adds delay
        completion_time_ms = receiver.schedule_verification(
            arrival_time_ms=self.state.current_time_ms,
            verify_duration_ms=verify_time,
        )

        self.state.schedule_event(
            time_ms=completion_time_ms,
            event_type=EventType.BLOCK_VALIDATED,
            payload={
                "block_hash": block_hash,
                "validator_id": receiver_id,
            },
        )

    def _handle_block_validated(self, event: Event) -> None:
        """Handle block validation: update state and forward to peers."""
        block_hash = event.payload["block_hash"]
        validator_id = event.payload["validator_id"]

        block = self.state.get_block_by_hash(block_hash)
        if not block:
            return

        # Record validation time
        block.validated_by[validator_id] = self.state.current_time_ms

        # Forward to peers (continue gossip)
        self.state.schedule_event(
            time_ms=self.state.current_time_ms,
            event_type=EventType.BLOCK_PROPAGATED,
            payload={"block_hash": block_hash, "sender_id": validator_id},
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _create_block(self, proposer: Node) -> Block:
        """Create a block filled with transactions.

        CAPACITY MODEL NOTE:
            For Solana, block_size_limit is in bytes and tx_size is in bytes —
            the division is physically correct.

            For Bitcoin (weight units) and Ethereum (gas), the engine treats
            block_size_limit and base_tx_overhead as generic "capacity units" and
            computes max_txs = capacity // per_tx_cost.  This is a deliberate
            simplification: the DES engine's purpose is to study PROPAGATION
            effects (bandwidth × block_bytes), not to replicate the exact
            Bitcoin/Ethereum transaction selection algorithm.  The static
            block-space analysis in `blockchain/chain_models.py` uses the
            precise per-chain formulas (SegWit weight, EVM gas) for throughput
            figures shown in the UI.
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        # Calculate transaction size with current signature algorithm
        sig_size = SIGNATURE_SIZES.get(self.config.signature_algorithm, 64)
        pk_size = PUBLIC_KEY_SIZES.get(self.config.signature_algorithm, 32)
        tx_overhead = self.chain_config.base_tx_overhead
        tx_size = tx_overhead + sig_size + pk_size

        # Fill block to capacity
        max_txs = self.block_size_limit // tx_size
        # No artificial cap — let Ed25519 fill to true 6 MB capacity
        # (was previously capped at 10,000 which under-filled small-sig blocks)

        transactions = [
            Transaction(
                tx_id=f"tx_{self.state.chain_height + 1}_{i}",
                size_bytes=tx_size,
                signature_algorithm=self.config.signature_algorithm,
                num_signatures=1,
                fee_satoshis=self.rng.randint(100, 10000),
                arrival_time_ms=self.state.current_time_ms,
            )
            for i in range(max_txs)
        ]

        block = Block(
            block_hash=f"block_{self.state.chain_height + 1}",
            parent_hash=self.state.chain_tip_hash,
            height=self.state.chain_height + 1,
            proposer_id=proposer.node_id,
            timestamp_ms=self.state.current_time_ms,
            transactions=transactions,
            signature_algorithm=self.config.signature_algorithm,
        )

        return block

    def _select_gossip_peers(self, sender: Node, block: Block) -> List[Node]:
        """Select peers for gossip propagation.

        Excludes nodes that have already seen the block.
        Uses random selection with configured fanout.
        """
        all_nodes = list(self.topology.nodes.values())
        available = [
            n for n in all_nodes
            if n.node_id != sender.node_id
            and not n.has_seen_block(block.block_hash)
        ]

        if not available:
            return []

        fanout = min(self.gossip_fanout, len(available))
        return self.rng.sample(available, fanout)

    def _compute_results(self) -> SimulationResult:
        """Compute metrics from completed simulation."""
        propagation_p50 = []
        propagation_p90 = []
        propagation_p95 = []
        block_sizes = []
        tx_counts = []

        total_nodes = self.topology.node_count()

        for block in self.state.blocks_proposed:
            p50 = block.propagation_percentile(50)
            p90 = block.propagation_percentile(90)
            p95 = block.propagation_percentile(95)

            if p50 is not None:
                propagation_p50.append(p50)
            if p90 is not None:
                propagation_p90.append(p90)
            if p95 is not None:
                propagation_p95.append(p95)

            block_sizes.append(block.size_bytes)
            tx_counts.append(block.tx_count)

        # Compute averages
        avg_p50 = sum(propagation_p50) / len(propagation_p50) if propagation_p50 else 0
        avg_p90 = sum(propagation_p90) / len(propagation_p90) if propagation_p90 else 0
        avg_p95 = sum(propagation_p95) / len(propagation_p95) if propagation_p95 else 0
        avg_block_size = sum(block_sizes) / len(block_sizes) if block_sizes else 0
        avg_tx_count = sum(tx_counts) / len(tx_counts) if tx_counts else 0

        # Compute stale rate
        # A block is "stale" if propagation p90 exceeds 90% of the block time
        # (industry standard: a block risks orphaning when it takes almost
        # the full slot to propagate, not merely half)
        stale_threshold = self.block_time_ms * 0.9
        stale_count = sum(1 for p in propagation_p90 if p > stale_threshold)
        stale_rate = stale_count / len(propagation_p90) if propagation_p90 else 0

        return SimulationResult(
            chain=self.config.chain,
            signature_algorithm=self.config.signature_algorithm,
            num_validators=self.config.num_validators,
            num_full_nodes=self.config.num_full_nodes,
            simulation_duration_ms=self.config.simulation_duration_ms,
            num_blocks=len(self.state.blocks_proposed),
            avg_block_size_bytes=avg_block_size,
            avg_txs_per_block=avg_tx_count,
            avg_propagation_p50_ms=avg_p50,
            avg_propagation_p90_ms=avg_p90,
            avg_propagation_p95_ms=avg_p95,
            min_propagation_ms=min(propagation_p90) if propagation_p90 else 0,
            max_propagation_ms=max(propagation_p90) if propagation_p90 else 0,
            stale_rate=stale_rate,
        )
