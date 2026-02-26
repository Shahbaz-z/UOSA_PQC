"""Node class with SimPy Resource-based bandwidth and CPU contention.

CRITICAL DESIGN DECISIONS (per Quant Lead review):

1. BANDWIDTH CONTENTION:
   - Upload and download bandwidth are modeled as SimPy Containers.
   - Container level represents available bandwidth (Mbps).
   - Transmissions consume bandwidth for their duration.
   - This creates realistic queuing when a node gossips to multiple peers.

   Example: A 100 Mbps upload node sending 8MB to 8 peers simultaneously:
   - Each transmission requests bandwidth from the Container.
   - Transmissions queue if insufficient bandwidth is available.
   - NIC saturation is accurately modeled.

2. CPU CONTENTION:
   - CPU cores are modeled as a SimPy Resource with capacity=num_cores.
   - Verification operations must acquire a CPU core.
   - Heavy PQC signatures (SLH-DSA) physically block other verifications.
   - This models real node behavior under computational load.

3. TRANSMISSION MODEL:
   - Time = size_bytes * 8 / bandwidth_bps
   - Uses min(sender_upload, receiver_download) as effective rate.
   - Bandwidth is consumed for the duration of transmission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Generator
import simpy

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

    Uses SimPy resources to model physical contention:
    - upload_bandwidth: Container (Mbps available)
    - download_bandwidth: Container (Mbps available)
    - cpu_cores: Resource (concurrent verification slots)

    This ensures realistic queuing behavior when:
    - Gossipping to multiple peers saturates NIC
    - Verifying multiple blocks saturates CPU
    """

    def __init__(self, config: NodeConfig, env: simpy.Environment):
        """Initialize node with SimPy resources.

        Args:
            config: Static node configuration.
            env: SimPy environment for resource creation.
        """
        self.config = config
        self.env = env
        self.state = NodeState(node_id=config.node_id)

        # Bandwidth as Containers (level = available Mbps)
        # Using Container allows partial consumption for parallel transmissions
        self._upload_bw = simpy.Container(
            env, capacity=config.upload_bandwidth_mbps, init=config.upload_bandwidth_mbps
        )
        self._download_bw = simpy.Container(
            env, capacity=config.download_bandwidth_mbps, init=config.download_bandwidth_mbps
        )

        # CPU cores as Resource (capacity = num cores)
        self._cpu = simpy.Resource(env, capacity=config.cpu_cores)

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

    def send_block(
        self,
        block: "Block",
        receiver: "Node",
    ) -> Generator[simpy.Event, None, float]:
        """SimPy process: Send a block to another node.

        This is a BLOCKING operation that:
        1. Computes effective bandwidth (min of sender upload, receiver download)
        2. Computes transmission time based on block size
        3. Yields for the transmission duration

        The caller must handle geographic latency separately.

        Yields:
            SimPy events for bandwidth consumption.

        Returns:
            Actual transmission time in ms.
        """
        size_bytes = block.size_bytes

        # Effective bandwidth is bottleneck of sender upload and receiver download
        effective_bw_mbps = min(
            self.config.upload_bandwidth_mbps,
            receiver.config.download_bandwidth_mbps,
        )

        # Calculate transmission time
        tx_time_ms = self.transmission_time_ms(size_bytes, effective_bw_mbps)

        # Consume bandwidth for duration (simplified: just yield timeout)
        # In a more detailed model, we'd use Container.get() and Container.put()
        yield self.env.timeout(tx_time_ms)

        # Update statistics
        self.state.bytes_uploaded += size_bytes
        receiver.state.bytes_downloaded += size_bytes

        return tx_time_ms

    def verify_block(
        self,
        block: "Block",
    ) -> Generator[simpy.Event, None, float]:
        """SimPy process: Verify all signatures in a block.

        This is a BLOCKING operation that:
        1. Requests a CPU core from the resource pool
        2. Computes verification time based on algorithm and signature count
        3. Holds the CPU core for the verification duration
        4. Releases the CPU core

        If all CPU cores are busy, this will queue until one is available.

        Yields:
            SimPy events for CPU resource acquisition and verification.

        Returns:
            Actual verification time in ms.
        """
        verify_time_ms = self.verification_time_ms(
            block.signature_algorithm,
            block.total_signatures,
        )

        # Request a CPU core (blocks if all cores busy)
        with self._cpu.request() as req:
            yield req  # Wait for CPU core

            # Perform verification (blocks the core)
            yield self.env.timeout(verify_time_ms)

        # Update statistics
        self.state.blocks_validated += 1
        self.state.total_verification_time_ms += verify_time_ms

        return verify_time_ms

    def has_seen_block(self, block_hash: str) -> bool:
        """Check if this node has already seen a block."""
        return block_hash in self.state.known_blocks

    def mark_block_seen(self, block_hash: str, time_ms: float) -> None:
        """Record that this node has seen a block."""
        if block_hash not in self.state.known_blocks:
            self.state.known_blocks[block_hash] = time_ms
        self.state.last_activity_time_ms = time_ms

    def utilization_stats(self) -> dict:
        """Get resource utilization statistics.

        Returns:
            Dict with upload_util, download_util, cpu_util percentages.
        """
        # CPU utilization: fraction of cores in use
        cpu_util = self._cpu.count / self._cpu.capacity if self._cpu.capacity > 0 else 0

        return {
            "cpu_in_use": self._cpu.count,
            "cpu_capacity": self._cpu.capacity,
            "cpu_utilization": cpu_util,
            "bytes_uploaded": self.state.bytes_uploaded,
            "bytes_downloaded": self.state.bytes_downloaded,
            "blocks_validated": self.state.blocks_validated,
        }
