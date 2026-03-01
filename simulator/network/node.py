"""Node class with analytical CPU-scheduling and bandwidth modelling.

CPU CONTENTION is modelled analytically via a min-heap of per-core
free-times (_core_free_at).  schedule_verification() assigns each
verification job to the earliest-free core without requiring SimPy.

TRANSMISSION TIME is computed from block size and effective bandwidth
(min of sender upload, receiver download) — no SimPy Container needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, List
import heapq

if TYPE_CHECKING:
    from simulator.network.propagation import Block


@dataclass(frozen=True)
class NodeConfig:
    """Static configuration for a validator node.

    Immutable after creation to ensure simulation reproducibility.
    """

    node_id: str
    region: str  # Geographic region (e.g., "US-East", "EU-West")

    # Bandwidth in Mbps (megabits per second)
    upload_bandwidth_mbps: float
    download_bandwidth_mbps: float

    # CPU configuration
    cpu_cores: int
    processing_power_factor: float  # 1.0 = baseline, 2.0 = twice as fast

    # Validator properties
    is_validator: bool  # Can propose blocks
    stake_weight: float  # For weighted leader selection (PoS)


@dataclass
class NodeState:
    """Dynamic state of a node during simulation.

    Mutable state that changes during simulation:
    - Mempool contents
    - Known blocks
    - Resource utilization metrics
    """

    node_id: str

    # Known blocks (block_hash -> first_seen_time_ms)
    known_blocks: dict = field(default_factory=dict)

    # Mempool (simplified for Phase 1)
    mempool_size: int = 0

    # Activity tracking
    last_activity_time_ms: float = 0.0
    blocks_validated: int = 0
    bytes_uploaded: int = 0
    bytes_downloaded: int = 0
    total_verification_time_ms: float = 0.0


class Node:
    """A network node with bandwidth and CPU constraints.

    CPU queuing is modelled analytically via _core_free_at (min-heap).
    Bandwidth is used only to compute transmission time; no SimPy
    containers are required.
    """

    def __init__(self, config: NodeConfig, env):
        """Initialize node.

        Args:
            config: Static node configuration.
            env: Simulation environment (kept for API compatibility).
        """
        self.config = config
        self.env = env
        self.state = NodeState(node_id=config.node_id)

        # ---- Analytical CPU scheduling queue ----
        # Tracks when each core becomes free (min-heap of timestamps).
        # Models the same queuing physics as a SimPy Resource without
        # requiring env.run(), integrating with the custom event loop.
        self._core_free_at: List[float] = [0.0] * config.cpu_cores
        heapq.heapify(self._core_free_at)

    @property
    def node_id(self) -> str:
        """Convenience accessor for node ID."""
        return self.config.node_id

    @property
    def region(self) -> str:
        """Convenience accessor for region."""
        return self.config.region

    def transmission_time_ms(self, size_bytes: int, bandwidth_mbps: float) -> float:
        """Calculate transmission time for given size and bandwidth.

        Args:
            size_bytes: Data size in bytes.
            bandwidth_mbps: Available bandwidth in Mbps.

        Returns:
            Transmission time in milliseconds.
        """
        if bandwidth_mbps <= 0:
            return float("inf")

        size_megabits = (size_bytes * 8) / 1_000_000  # Convert bytes to megabits
        time_seconds = size_megabits / bandwidth_mbps
        return time_seconds * 1000  # Convert to ms

    def verification_time_ms(self, algorithm: str, num_signatures: int) -> float:
        """Calculate verification time for signatures.

        Uses VERIFICATION_PROFILES from blockchain.verification module.
        Adjusts for processing_power_factor (higher = faster).

        Args:
            algorithm: Signature algorithm name.
            num_signatures: Number of signatures to verify.

        Returns:
            Verification time in milliseconds.
        """
        from blockchain.verification import VERIFICATION_PROFILES

        profile = VERIFICATION_PROFILES.get(algorithm)
        if not profile:
            # Unknown algorithm: use conservative estimate (500 us/sig)
            base_time_us = 500.0 * num_signatures
        else:
            base_time_us = profile.verify_time_us * num_signatures

        # Adjust for processing power (higher factor = faster)
        adjusted_time_us = base_time_us / self.config.processing_power_factor

        return adjusted_time_us / 1000  # Convert to ms

    def schedule_verification(
        self, arrival_time_ms: float, verify_duration_ms: float
    ) -> float:
        """Schedule a verification job on the earliest-free CPU core.

        Models CPU queuing analytically: if all cores are busy the job
        waits until the earliest core finishes its current work.

        Args:
            arrival_time_ms: Simulation time when the block arrives.
            verify_duration_ms: Pure compute time for this verification.

        Returns:
            Absolute simulation time when verification completes.
        """
        # Pop the earliest-freeing core
        earliest_free = heapq.heappop(self._core_free_at)

        # Job cannot start before arrival or before the core is free
        start_time = max(arrival_time_ms, earliest_free)
        completion_time = start_time + verify_duration_ms

        # Push updated free-time back into the heap
        heapq.heappush(self._core_free_at, completion_time)

        # Update statistics
        self.state.blocks_validated += 1
        self.state.total_verification_time_ms += verify_duration_ms

        return completion_time

    def has_seen_block(self, block_hash: str) -> bool:
        """Check if this node has already seen a block."""
        return block_hash in self.state.known_blocks

    def mark_block_seen(self, block_hash: str, time_ms: float) -> None:
        """Record that this node has seen a block."""
        if block_hash not in self.state.known_blocks:
            self.state.known_blocks[block_hash] = time_ms
        self.state.last_activity_time_ms = time_ms

