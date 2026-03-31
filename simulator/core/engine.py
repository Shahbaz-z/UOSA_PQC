"""Discrete Event Simulation (DES) engine for blockchain network propagation.

ENGINE HIERARCHY
================
This codebase has TWO engine classes with a strict parent/child relationship:

  simulator.core.engine        → DESEngine  (Phase 1 — propagation only)
  simulator.core.phase2_engine → Phase2Engine  (Phase 2/3 — extends DESEngine)

┌─────────────────────────────────────────────────────────────────────────┐
│  DESEngine  (this file)                                                 │
│  ─────────────────────────────────────────────────────────────────────  │
│  • Heapq-based analytical event loop (SLOT_TICK → BLOCK_PROPOSED →     │
│    BLOCK_PROPAGATED → BLOCK_RECEIVED → BLOCK_VALIDATED)                 │
│  • NIC-contention model, CPU-core scheduling, chain-specific routing    │
│  • Returns: SimulationResult (propagation, stale rate, TPS)             │
│  • Use for: propagation-only runs, calibration baselines, new modules   │
└───────────────────────┬─────────────────────────────────────────────────┘
                        │  Phase2Engine WRAPS DESEngine via composition.
                        │  It constructs a DESEngine internally and
                        │  monkey-patches _create_block and
                        │  _handle_block_received at runtime.
                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase2Engine  (simulator/core/phase2_engine.py)                        │
│  ─────────────────────────────────────────────────────────────────────  │
│  • SimPy-compatible stochastic Poisson transaction arrivals             │
│  • GlobalMempool with fee-rate eviction (bounded at 100 MB)             │
│  • Heterogeneous blocks (mixed classical + PQC algorithm fractions)     │
│  • Per-transaction verification with CPU resource locking               │
│  • Phase G: DynamicFeeMarket, vote transaction overhead (Solana)        │
│  • Returns: Dict (all Phase 1 metrics + verification + mempool + fees)  │
│  • Use for: Monte Carlo sweeps, sensitivity analysis, fee experiments   │
└─────────────────────────────────────────────────────────────────────────┘

WHEN TO USE WHICH
─────────────────
• DESEngine alone       — calibration, propagation impact, new module integration tests
• Phase2Engine          — pqc_fraction sweeps, mempool dynamics, fee market experiments
• Both engines          — DualSigConfig.sim_configs() feeds Phase2Config for migration runs

DESIGN NOTES

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
from simulator.network.routing import (
    RoutingStrategy,
    GossipRouting,
    get_routing_strategy,
)
from simulator.chains.base import get_chain_config, ChainConfig
from simulator.chains.bitcoin_specific import BitcoinTxModel, DEFAULT_BITCOIN_TX_MODEL
from simulator.chains.ethereum_specific import EthereumTxModel, DEFAULT_ETHEREUM_TX_MODEL
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

    # Realism flags (Phase B upgrades)
    nic_contention_enabled: bool = True   # Model upload bandwidth sharing
    use_chain_routing: bool = True        # Use chain-specific routing strategy


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

        # Routing strategy
        if config.use_chain_routing:
            self.routing = get_routing_strategy(config.chain)
        else:
            self.routing = GossipRouting(fanout=self.gossip_fanout)

        # NIC contention flag
        self.nic_contention_enabled = config.nic_contention_enabled

        # Network components
        self.topology = NetworkTopology(rng=self.rng)
        self.state = SimulationState(end_time_ms=config.simulation_duration_ms)

        # Set to True to populate state.completed_events for debugging.
        # Off by default: a 5-minute Solana run produces ~280k events and
        # completed_events is never read in normal result computation.
        self._debug_keep_events: bool = False

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

            # completed_events is only populated in debug mode to avoid
            # unbounded memory growth (~280k events in a 5-min Solana run).
            if getattr(self, "_debug_keep_events", False):
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

        # Create block.
        # NOTE (Bug 5 — latent, not a current defect):
        # register_block() advances state.chain_height and state.chain_tip_hash
        # immediately at proposal time, before the block is validated by any
        # peer.  For the current single-proposer linear chain model this is
        # correct: there is only one proposer per slot, so chain_height always
        # reflects the latest proposed (and eventually validated) block.
        # If concurrent proposals or fork-choice are ever added, register_block()
        # must be deferred until the block achieves finality (quorum validation)
        # to avoid chain_height reflecting unvalidated orphans.
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
        """Handle block propagation: send to peers via routing strategy.

        Phase B upgrades:
        1. Uses chain-specific routing (Turbine, compact block, ETH hybrid)
        2. Models NIC contention: upload bandwidth shared across concurrent sends
        3. Uses actual byte sizes for propagation (not gas/weight units)
        """
        block_hash = event.payload["block_hash"]
        sender_id = event.payload["sender_id"]
        sender = self.topology.get_node(sender_id)

        block = self.state.get_block_by_hash(block_hash)
        if not block:
            return

        # Turbine multi-layer delay: each relay layer (1+) adds a base network
        # processing delay before forwarding to the next layer.  This models
        # the sequential nature of Turbine's tree structure where layer N must
        # fully receive and validate before layer N+1 can start.
        # Delay ≈ 1/2 of the minimum inter-region latency (20ms) = 10ms per hop.
        # Source: Solana validator gossip observed latency per turbine layer
        # https://docs.solana.com/consensus/turbine-block-propagation
        propagation_layer = event.payload.get("propagation_layer", 0)
        turbine_layer_delay_ms = 0.0
        if (
            propagation_layer > 0
            and hasattr(self, "routing")
            and self.routing.__class__.__name__ == "TurbineRouting"
        ):
            # 10ms per hop beyond layer 0 (intra-datacenter forwarding overhead)
            turbine_layer_delay_ms = propagation_layer * 10.0

        # Determine which nodes already have the block
        already_seen = set(block.first_seen_by.keys())

        # Use routing strategy to plan propagation
        tasks = self.routing.plan_propagation(
            sender=sender,
            block=block,
            all_nodes=self.topology.nodes,
            already_seen=already_seen,
            rng=self.rng,
        )

        if not tasks:
            return

        # Number of concurrent sends (for NIC contention)
        num_concurrent = len(tasks)

        # NIC CONTENTION — correct concurrent model:
        # When a node sends the same block to K peers simultaneously, the NIC
        # bandwidth is shared K ways.  All K sends START at the same time (the
        # NIC free-time), and all K sends FINISH at the same time (one block-time
        # later at the shared rate).  Calling schedule_upload() once per peer in
        # the loop would serialise them: peer 2 cannot start until peer 1 finishes,
        # giving peer K a receive_time K× longer than peer 1 — which is wrong for
        # parallel sends.
        #
        # Correct approach: capture nic_start ONCE before the loop (all concurrent
        # sends start together), then call schedule_upload() ONCE to advance
        # _upload_free_at by the batch duration.
        #
        # The block size for the batch is the representative task size (all tasks
        # in one BLOCK_PROPAGATED event carry the same block — different only in
        # announcement vs full for EthHybrid, but that is handled per-task below).
        representative_task = tasks[0]
        if self.nic_contention_enabled:
            # Compute shared NIC start time (respects back-to-back sends from
            # earlier BLOCK_PROPAGATED events via _upload_free_at)
            per_peer_bw_sender = sender.config.upload_bandwidth_mbps / max(1, num_concurrent)
            if per_peer_bw_sender > 0:
                size_megabits_repr = (representative_task.size_bytes * 8) / 1_000_000
                batch_tx_time_ms   = (size_megabits_repr / per_peer_bw_sender) * 1000
                # Schedule the whole batch as one NIC operation
                batch_finish_time  = sender.schedule_upload(
                    start_time_ms=self.state.current_time_ms,
                    size_bytes=representative_task.size_bytes,
                    num_concurrent=num_concurrent,
                )
                # All concurrent sends share this start time
                nic_batch_start = max(
                    self.state.current_time_ms,
                    batch_finish_time - batch_tx_time_ms,
                )
            else:
                nic_batch_start = self.state.current_time_ms
        else:
            nic_batch_start = self.state.current_time_ms

        for task in tasks:
            receiver = self.topology.get_node(task.receiver_id)
            if receiver.has_seen_block(block_hash):
                continue

            # Geographic latency
            geo_latency = self.topology.sample_latency(
                sender.config.region, receiver.config.region
            )

            # Transmission time: per-task size at effective bottleneck bandwidth
            if self.nic_contention_enabled:
                per_peer_bw  = sender.config.upload_bandwidth_mbps / max(1, num_concurrent)
                effective_bw = min(per_peer_bw, receiver.config.download_bandwidth_mbps)
                if effective_bw <= 0:
                    continue
                size_megabits = (task.size_bytes * 8) / 1_000_000
                tx_time_ms    = (size_megabits / effective_bw) * 1000
                # All concurrent sends start at the same NIC-batch start time
                receive_time  = nic_batch_start + geo_latency + tx_time_ms + turbine_layer_delay_ms
            else:
                per_peer_bw  = sender.config.upload_bandwidth_mbps
                effective_bw = min(per_peer_bw, receiver.config.download_bandwidth_mbps)
                if effective_bw <= 0:
                    continue
                size_megabits = (task.size_bytes * 8) / 1_000_000
                tx_time_ms    = (size_megabits / effective_bw) * 1000
                receive_time  = self.state.current_time_ms + geo_latency + tx_time_ms + turbine_layer_delay_ms

            self.state.schedule_event(
                time_ms=receive_time,
                event_type=EventType.BLOCK_RECEIVED,
                payload={
                    "block_hash": block_hash,
                    "receiver_id": task.receiver_id,
                    "sender_id": sender_id,
                    # True for Ethereum announcement peers: they receive the block
                    # hash first (100 B) and must fetch the full block separately.
                    # first_seen_by is NOT recorded until the full block arrives.
                    "is_eth_announcement": task.is_eth_announcement,
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

        # Ethereum two-phase retrieval:
        # An announcement-only message (100 bytes: hash + number) signals that
        # the full block exists, but the peer does not yet have the block data.
        # The peer must request the full block from the sender.  We model this
        # as: announcement → scheduling a second BLOCK_RECEIVED event with the
        # full block size, then returning without recording first_seen_by.
        # Only when the full block arrives is the peer considered to have the block.
        is_eth_announcement = event.payload.get("is_eth_announcement", False)
        if is_eth_announcement:
            sender_id = event.payload.get("sender_id")
            sender = self.topology.get_node(sender_id) if sender_id else None
            if sender and block:
                # Geographic latency for the request round-trip (one way)
                geo_latency = self.topology.sample_latency(
                    sender.config.region, receiver.config.region
                )
                # Full block retrieval: receiver downloads from sender
                effective_bw = min(
                    sender.config.upload_bandwidth_mbps,
                    receiver.config.download_bandwidth_mbps,
                )
                if effective_bw > 0:
                    size_megabits = (block.size_bytes * 8) / 1_000_000
                    tx_time_ms = (size_megabits / effective_bw) * 1000
                    # Full Ethereum block retrieval includes two geo_latency legs:
                    #   1. Receiver sends GETBLOCKBODIES request → one-way geo_latency
                    #   2. Sender processes and returns full block → tx_time_ms
                    # The previous model had only one geo_latency, missing the
                    # request leg.  For cross-continental peers (~150ms RTT) this
                    # underestimated retrieval time by up to 2× geo_latency.
                    # Reference: Ethereum devp2p eth protocol (GETBLOCKBODIES)
                    retrieval_time = (
                        self.state.current_time_ms
                        + geo_latency   # announcement → peer
                        + geo_latency   # request leg: peer → sender
                        + tx_time_ms    # full block download
                    )
                    self.state.schedule_event(
                        time_ms=retrieval_time,
                        event_type=EventType.BLOCK_RECEIVED,
                        payload={
                            "block_hash": block_hash,
                            "receiver_id": receiver_id,
                            "sender_id": sender_id,
                            "is_eth_announcement": False,  # Full block this time
                        },
                    )
            return  # Don't record first_seen_by — wait for full block

        # Record first seen time (full block received)
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

        # Forward to peers (continue gossip).
        # Track propagation_layer for Turbine multi-hop delay accounting.
        # Each relay hop increments the layer counter so _handle_block_propagated
        # can add Turbine's sequential layer delay on top of normal transmission.
        prev_layer = event.payload.get("propagation_layer", 0)
        self.state.schedule_event(
            time_ms=self.state.current_time_ms,
            event_type=EventType.BLOCK_PROPAGATED,
            payload={
                "block_hash": block_hash,
                "sender_id": validator_id,
                "propagation_layer": prev_layer + 1,  # relay nodes are layer 1+
            },
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _create_block(self, proposer: Node) -> Block:
        """Create a block filled with transactions.

        CAPACITY MODEL:
            Each chain uses its native capacity unit for block-filling:
            - Solana: bytes (block_size_limit = 6 MB)
            - Bitcoin: weight units (4 MWU with SegWit witness discount)
            - Ethereum: gas (30M gas limit)

            For PROPAGATION, we compute the actual byte size separately
            using chain-specific models. This ensures propagation
            delays reflect real network load, not gas/weight abstractions.

        Phase G upgrade: Uses BitcoinTxModel (SegWit weight) and
        EthereumTxModel (gas metering) for accurate capacity calculation.
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        sig_size = SIGNATURE_SIZES.get(self.config.signature_algorithm, 64)
        pk_size = PUBLIC_KEY_SIZES.get(self.config.signature_algorithm, 32)

        chain = self.config.chain.lower()

        if chain == "bitcoin":
            # Bitcoin: capacity in weight units, propagation in bytes
            btc_model = DEFAULT_BITCOIN_TX_MODEL
            tx_weight = btc_model.tx_weight(sig_size, pk_size)
            max_txs = self.block_size_limit // tx_weight if tx_weight > 0 else 0
            tx_prop_bytes = btc_model.tx_bytes(sig_size, pk_size)

        elif chain == "ethereum":
            # Ethereum: capacity in gas, propagation in bytes
            eth_model = DEFAULT_ETHEREUM_TX_MODEL
            tx_gas = eth_model.tx_gas(sig_size, pk_size)
            max_txs = self.block_size_limit // tx_gas if tx_gas > 0 else 0
            tx_prop_bytes = eth_model.tx_bytes(sig_size, pk_size)

        else:
            # Solana (and fallback): capacity and propagation both in bytes
            tx_overhead = self.chain_config.base_tx_overhead
            tx_capacity_cost = tx_overhead + sig_size + pk_size
            max_txs = self.block_size_limit // tx_capacity_cost if tx_capacity_cost > 0 else 0
            prop_overhead = self.chain_config.propagation_tx_overhead_bytes
            if prop_overhead == 0:
                prop_overhead = tx_overhead
            tx_prop_bytes = prop_overhead + sig_size + pk_size

        # Apply realistic block utilisation: real-world blocks are not always full.
        # Bitcoin averages ~65%, Ethereum ~70%, Solana ~40%.
        # We draw a lognormal utilisation factor with mean = target and sigma=0.15,
        # clamped to [0.2, 1.0], to model natural variance around the target.
        # This is critical for calibration: without this, block_utilisation always
        # ≈ 1.0 and the 25% tolerance band trivially passes at 100%.
        _CHAIN_UTIL_TARGET = {"bitcoin": 0.65, "ethereum": 0.70, "solana": 0.40}
        _util_target = _CHAIN_UTIL_TARGET.get(chain, 0.65)
        import math as _math
        _util_sigma = 0.15
        _util_mu = _math.log(max(_util_target, 0.01))
        _util_sample = self.rng.lognormvariate(_util_mu, _util_sigma)
        _block_utilisation = max(0.20, min(1.0, _util_sample / _util_target * _util_target))
        max_txs = max(1, int(max_txs * _block_utilisation))

        transactions = [
            Transaction(
                tx_id=f"tx_{self.state.chain_height + 1}_{i}",
                size_bytes=tx_prop_bytes,  # Actual bytes for propagation
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
        """[DEPRECATED — dead code] Legacy gossip peer selection.

        The primary propagation path uses self.routing.plan_propagation()
        in _handle_block_propagated(), which dispatches to chain-specific
        routing strategies (Turbine, CompactBlock, EthHybrid).

        Phase2Engine does NOT monkey-patch propagation, so this method is
        never called in any current code path.  It is retained only because
        removing it would require a minor version bump to avoid breaking any
        downstream forks that may reference it directly.

        DO NOT use in new code.  Use self.routing.plan_propagation() instead.
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
