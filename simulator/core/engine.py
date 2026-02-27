"""Discrete Event Simulation engine for blockchain network propagation.

CRITICAL DESIGN (per Quant Lead review):

1. BANDWIDTH CONTENTION:
   - Nodes cannot gossip to infinite peers simultaneously.
   - Upload bandwidth is a finite resource.
   - When a node sends a block, it consumes bandwidth for the transmission duration.
   - Subsequent transmissions must wait (queue) if bandwidth is saturated.

2. CPU CONTENTION:
   - Nodes cannot verify infinite signatures in parallel.
   - CPU cores are finite resources.
   - Heavy PQC signatures (SLH-DSA: 3-8ms) physically block verification of
     subsequent blocks.
   - This creates realistic node saturation under PQC load.

3. EVENT LOOP:
   - Uses SimPy for process-based discrete event simulation.
   - Events are scheduled on a priority queue (heapq).
   - Time advances discretely between events.
   - All randomness is seeded for reproducibility.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import simpy

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
    num_validators: int = 100
    num_full_nodes: int = 400
    simulation_duration: float = 600.0  # seconds
    random_seed: int = 42
    pqc_adoption_fraction: float = 0.0  # fraction of nodes using PQC
    mempool_eviction: bool = False       # enable economic mempool eviction


class DESEngine:
    """Discrete Event Simulation engine."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.env = simpy.Environment()
        self.state = SimulationState()
        self.nodes: Dict[str, Node] = {}
        self.topology: Optional[NetworkTopology] = None
        self.chain_config: Optional[ChainConfig] = None
        self._rng = random.Random(config.random_seed)
        self._block_counter = 0
        self._tx_counter = 0
        self._results: List[SimulationResult] = []

    def setup(self) -> None:
        """Initialize nodes, topology, and chain configuration."""
        self.chain_config = get_chain_config(self.config.chain)
        self._setup_nodes()
        self._setup_topology()

    def _setup_nodes(self) -> None:
        """Create validator and full nodes with realistic configurations."""
        # Create validators
        for i in range(self.config.num_validators):
            region = self._rng.choices(
                list(REGIONS.keys()),
                weights=list(region_distribution.values()),
            )[0]
            bw_config = sample_validator_config(region, rng=self._rng)
            node_config = NodeConfig(
                node_id=f"validator_{i}",
                node_type="validator",
                region=region,
                upload_bandwidth_mbps=bw_config.upload_mbps,
                download_bandwidth_mbps=bw_config.download_mbps,
                cpu_cores=bw_config.cpu_cores,
                signature_algorithm=self.config.signature_algorithm,
                is_pqc=(
                    self._rng.random() < self.config.pqc_adoption_fraction
                ),
            )
            self.nodes[node_config.node_id] = Node(self.env, node_config)

        # Create full nodes
        for i in range(self.config.num_full_nodes):
            region = self._rng.choices(
                list(REGIONS.keys()),
                weights=list(region_distribution.values()),
            )[0]
            bw_config = sample_full_node_config(region, rng=self._rng)
            node_config = NodeConfig(
                node_id=f"full_node_{i}",
                node_type="full_node",
                region=region,
                upload_bandwidth_mbps=bw_config.upload_mbps,
                download_bandwidth_mbps=bw_config.download_mbps,
                cpu_cores=bw_config.cpu_cores,
                signature_algorithm=self.config.signature_algorithm,
                is_pqc=(
                    self._rng.random() < self.config.pqc_adoption_fraction
                ),
            )
            self.nodes[node_config.node_id] = Node(self.env, node_config)

    def _setup_topology(self) -> None:
        """Build network topology with realistic peer connections."""
        self.topology = NetworkTopology(
            nodes=list(self.nodes.values()),
            rng=self._rng,
        )
        self.topology.build()

    def run(self) -> List[SimulationResult]:
        """Execute the simulation."""
        self.setup()
        self.env.process(self._block_producer())
        self.env.process(self._tx_generator())
        self.env.run(until=self.config.simulation_duration)
        return self._results

    def _block_producer(self):
        """Generate blocks at chain-appropriate intervals."""
        chain = self.chain_config
        while True:
            # Wait for block time with jitter
            block_interval = self._rng.expovariate(1.0 / chain.block_time_s)
            yield self.env.timeout(block_interval)

            # Select a random validator as block producer
            validators = [
                n for n in self.nodes.values() if n.config.node_type == "validator"
            ]
            if not validators:
                continue
            producer = self._rng.choice(validators)

            # Build block from mempool
            block = self._build_block(producer)
            if block is None:
                continue

            # Record block production time
            block.produced_at = self.env.now

            # Propagate block through network
            self.env.process(
                self._propagate_block(producer, block)
            )

    def _build_block(self, producer: Node) -> Optional[Block]:
        """Construct a block from pending transactions."""
        pending_txs = self.state.get_pending_transactions()
        if not pending_txs:
            return None

        chain = self.chain_config

        # Fill block to byte-size capacity (no artificial tx cap)
        selected_txs = []
        current_size = 0
        for tx in pending_txs:
            tx_size = tx.size_bytes
            if current_size + tx_size > chain.max_block_size_bytes:
                break
            selected_txs.append(tx)
            current_size += tx_size

        if not selected_txs:
            return None

        self._block_counter += 1
        return Block(
            block_id=f"block_{self._block_counter}",
            transactions=selected_txs,
            producer_id=producer.config.node_id,
            size_bytes=current_size,
            signature_algorithm=self.config.signature_algorithm,
        )

    def _propagate_block(self, origin: Node, block: Block):
        """Propagate a block from origin node through the network."""
        visited = {origin.config.node_id}
        queue = [(origin, 0.0)]  # (node, arrival_time)

        propagation_times = []

        while queue:
            current_node, arrival_time = queue.pop(0)

            # Schedule verification at this node
            verify_delay = yield self.env.process(
                current_node.schedule_verification(block)
            )

            # Propagate to peers
            peers = self.topology.get_peers(current_node.config.node_id)
            for peer in peers:
                if peer.config.node_id in visited:
                    continue
                visited.add(peer.config.node_id)

                # Calculate transmission delay
                tx_delay = self._calc_transmission_delay(
                    current_node, peer, block.size_bytes
                )
                # Calculate network latency
                net_latency = self.topology.get_latency(
                    current_node.config.node_id,
                    peer.config.node_id,
                )

                peer_arrival = arrival_time + verify_delay + tx_delay + net_latency
                propagation_times.append(peer_arrival)
                queue.append((peer, peer_arrival))

        # Record propagation statistics
        if propagation_times:
            propagation_times.sort()
            n = len(propagation_times)
            p50 = propagation_times[int(n * 0.50)]
            p90 = propagation_times[int(n * 0.90)]

            result = SimulationResult(
                block_id=block.block_id,
                produced_at=block.produced_at,
                num_txs=len(block.transactions),
                block_size_bytes=block.size_bytes,
                propagation_p50_ms=p50 * 1000,
                propagation_p90_ms=p90 * 1000,
                signature_algorithm=self.config.signature_algorithm,
                chain=self.config.chain,
            )
            self._results.append(result)

            # FIX #1: Use 0.9 × block_time as stale threshold (was 0.5)
            stale_threshold = self.chain_config.block_time_s * 0.9
            if p90 > stale_threshold:
                self.state.record_stale_block(block.block_id)
                logger.warning(
                    "Stale block %s: p90=%.3fs > threshold=%.3fs",
                    block.block_id, p90, stale_threshold,
                )

    def _calc_transmission_delay(self, sender: Node, receiver: Node, size_bytes: int) -> float:
        """Calculate transmission delay based on bandwidth contention."""
        # Use sender's upload bandwidth (the bottleneck)
        upload_bps = sender.config.upload_bandwidth_mbps * 1e6 / 8  # bytes per second
        base_delay = size_bytes / upload_bps

        # Add queuing delay from bandwidth contention
        queue_delay = sender.get_bandwidth_queue_delay(size_bytes)
        return base_delay + queue_delay

    def _tx_generator(self):
        """Generate transactions at a realistic rate."""
        chain = self.chain_config
        while True:
            # Poisson arrival process
            inter_arrival = self._rng.expovariate(chain.tx_rate)
            yield self.env.timeout(inter_arrival)

            self._tx_counter += 1
            tx = Transaction(
                tx_id=f"tx_{self._tx_counter}",
                size_bytes=self._rng.randint(
                    chain.min_tx_size_bytes, chain.max_tx_size_bytes
                ),
                fee=self._rng.uniform(chain.min_fee, chain.max_fee),
                signature_algorithm=self.config.signature_algorithm,
            )
            self.state.add_transaction(tx)
