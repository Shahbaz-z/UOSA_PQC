"""Phase 2/3 DES Engine: Stochastic PQC Shock + Economic Mempool Eviction.

Extends the Phase 1 DES engine with:
1. Stochastic PQC adoption shock (gradual or sudden transition)
2. Economic mempool eviction (fee-based priority queue)
3. Monte Carlo sweep support
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import simpy
import numpy as np

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.network.node import Node, NodeConfig
from simulator.network.propagation import Block, Transaction
from simulator.results import SimulationResult
from simulator.models.bandwidth import (
    sample_validator_config,
    sample_full_node_config,
    region_distribution,
)
from simulator.network.topology import REGIONS

logger = logging.getLogger(__name__)


@dataclass
class Phase2Config:
    """Additional config for Phase 2/3 simulation."""

    # PQC shock parameters
    pqc_shock_start: float = 100.0      # simulation time when PQC shock begins
    pqc_shock_duration: float = 200.0   # duration of transition period
    pqc_shock_type: str = "gradual"      # "gradual" or "sudden"
    target_pqc_fraction: float = 1.0    # final PQC adoption fraction

    # Economic mempool eviction
    mempool_max_size: int = 50_000      # max transactions in mempool
    eviction_policy: str = "fee"        # "fee" or "fifo"

    # Monte Carlo
    num_monte_carlo_runs: int = 10
    mc_seeds: Optional[List[int]] = None


class Phase2Engine(DESEngine):
    """Phase 2/3 DES engine with PQC shock and mempool eviction."""

    def __init__(self, config: SimulationConfig, phase2_config: Phase2Config):
        super().__init__(config)
        self.p2_config = phase2_config
        self._pqc_fraction_current = config.pqc_adoption_fraction
        self._mempool_evictions = 0

    def run(self) -> List[SimulationResult]:
        """Execute the Phase 2 simulation with shock and eviction."""
        self.setup()
        self.env.process(self._block_producer())
        self.env.process(self._tx_generator())
        self.env.process(self._pqc_shock_driver())
        self.env.run(until=self.config.simulation_duration)
        return self._results

    def _pqc_shock_driver(self):
        """Drive PQC adoption shock over time."""
        p2 = self.p2_config

        # Wait until shock starts
        yield self.env.timeout(p2.pqc_shock_start)
        logger.info("PQC shock starting at t=%.1f", self.env.now)

        if p2.pqc_shock_type == "sudden":
            # Instant transition
            self._apply_pqc_fraction(p2.target_pqc_fraction)
            yield self.env.timeout(0)
        else:
            # Gradual transition over shock_duration
            steps = 20
            dt = p2.pqc_shock_duration / steps
            for step in range(steps + 1):
                frac = step / steps
                target = (
                    self._pqc_fraction_current
                    + frac * (p2.target_pqc_fraction - self._pqc_fraction_current)
                )
                self._apply_pqc_fraction(target)
                yield self.env.timeout(dt)

        logger.info("PQC shock complete at t=%.1f", self.env.now)

    def _apply_pqc_fraction(self, fraction: float) -> None:
        """Update what fraction of nodes use PQC signatures."""
        self._pqc_fraction_current = fraction
        all_nodes = list(self.nodes.values())
        self._rng.shuffle(all_nodes)
        cutoff = int(len(all_nodes) * fraction)
        for i, node in enumerate(all_nodes):
            node.config.is_pqc = i < cutoff
            if node.config.is_pqc:
                node.config.signature_algorithm = self.config.signature_algorithm
            else:
                node.config.signature_algorithm = "Ed25519"

    def _build_block(self, producer: Node) -> Optional[Block]:
        """Build block with economic fee-priority ordering."""
        pending_txs = self.state.get_pending_transactions()
        if not pending_txs:
            return None

        chain = self.chain_config

        # Sort by fee (highest first) for economic ordering
        if self.p2_config.eviction_policy == "fee":
            pending_txs = sorted(pending_txs, key=lambda t: t.fee, reverse=True)

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

        # Apply mempool eviction if over limit
        if len(pending_txs) > self.p2_config.mempool_max_size:
            # Evict lowest-fee transactions
            evict_count = len(pending_txs) - self.p2_config.mempool_max_size
            if self.p2_config.eviction_policy == "fee":
                to_evict = sorted(pending_txs, key=lambda t: t.fee)[:evict_count]
            else:
                to_evict = pending_txs[-evict_count:]
            for tx in to_evict:
                self.state.remove_transaction(tx.tx_id)
            self._mempool_evictions += evict_count

        self._block_counter += 1
        return Block(
            block_id=f"block_{self._block_counter}",
            transactions=selected_txs,
            producer_id=producer.config.node_id,
            size_bytes=current_size,
            signature_algorithm=self.config.signature_algorithm,
        )

    def _propagate_block(self, origin: Node, block: Block):
        """Propagate block and record Phase 2 statistics."""
        visited = {origin.config.node_id}
        queue = [(origin, 0.0)]
        propagation_times = []

        while queue:
            current_node, arrival_time = queue.pop(0)
            verify_delay = yield self.env.process(
                current_node.schedule_verification(block)
            )

            peers = self.topology.get_peers(current_node.config.node_id)
            for peer in peers:
                if peer.config.node_id in visited:
                    continue
                visited.add(peer.config.node_id)

                tx_delay = self._calc_transmission_delay(
                    current_node, peer, block.size_bytes
                )
                net_latency = self.topology.get_latency(
                    current_node.config.node_id,
                    peer.config.node_id,
                )
                peer_arrival = arrival_time + verify_delay + tx_delay + net_latency
                propagation_times.append(peer_arrival)
                queue.append((peer, peer_arrival))

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
                pqc_fraction=self._pqc_fraction_current,
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

    def get_mempool_eviction_count(self) -> int:
        """Return total number of evicted transactions."""
        return self._mempool_evictions


def run_monte_carlo(
    base_config: SimulationConfig,
    phase2_config: Phase2Config,
    seeds: Optional[List[int]] = None,
) -> List[Dict]:
    """Run Monte Carlo sweep and aggregate results."""
    if seeds is None:
        seeds = list(range(phase2_config.num_monte_carlo_runs))

    all_results = []
    for seed in seeds:
        cfg = SimulationConfig(
            chain=base_config.chain,
            signature_algorithm=base_config.signature_algorithm,
            num_validators=base_config.num_validators,
            num_full_nodes=base_config.num_full_nodes,
            simulation_duration=base_config.simulation_duration,
            random_seed=seed,
            pqc_adoption_fraction=base_config.pqc_adoption_fraction,
        )
        engine = Phase2Engine(cfg, phase2_config)
        results = engine.run()

        if results:
            import numpy as np
            p50s = [r.propagation_p50_ms for r in results]
            p90s = [r.propagation_p90_ms for r in results]
            block_sizes = [r.block_size_bytes for r in results]
            tx_counts = [r.num_txs for r in results]

            all_results.append({
                "seed": seed,
                "chain": base_config.chain,
                "pqc_fraction": base_config.pqc_adoption_fraction,
                "num_blocks": len(results),
                "avg_propagation_p50_ms": float(np.mean(p50s)),
                "avg_propagation_p90_ms": float(np.mean(p90s)),
                "std_propagation_p90_ms": float(np.std(p90s)),
                "avg_block_size_bytes": float(np.mean(block_sizes)),
                "avg_txs_per_block": float(np.mean(tx_counts)),
                "mempool_evictions": engine.get_mempool_eviction_count(),
                "pqc_shock_type": phase2_config.pqc_shock_type,
            })
            logger.info(
                "MC run seed=%d: %d blocks, avg_p90=%.1fms",
                seed, len(results), float(np.mean(p90s))
            )

    return all_results
