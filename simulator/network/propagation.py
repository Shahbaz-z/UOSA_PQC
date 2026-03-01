"""Block and Transaction dataclasses for network propagation modeling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Transaction:
    """Minimal transaction representation for simulation.

    Models the key properties affecting network propagation:
    - Size (affects bandwidth consumption)
    - Signature algorithm (affects verification time)
    - Fee (for future Phase 3 prioritization)
    """

    tx_id: str
    size_bytes: int
    signature_algorithm: str
    num_signatures: int
    fee_satoshis: int  # Normalized fee unit across chains
    arrival_time_ms: float

    # Computed: fee rate for prioritization
    priority: float = field(default=0.0, compare=False)

    def __post_init__(self):
        """Compute priority (fee per byte)."""
        if self.size_bytes > 0:
            self.priority = self.fee_satoshis / self.size_bytes


@dataclass
class Block:
    """A block in the simulation.

    Tracks propagation through the network via first_seen_by and validated_by
    dictionaries, enabling post-simulation analysis of propagation delays.
    """

    block_hash: str
    parent_hash: str
    height: int
    proposer_id: str
    timestamp_ms: float  # Simulation time when proposed
    transactions: List[Transaction] = field(default_factory=list)

    # Primary signature algorithm (for verification time estimation)
    signature_algorithm: str = "Ed25519"

    # Propagation tracking (populated during simulation)
    # Maps node_id -> simulation time when event occurred
    first_seen_by: Dict[str, float] = field(default_factory=dict)
    validated_by: Dict[str, float] = field(default_factory=dict)

    # Computed fields (set in __post_init__)
    size_bytes: int = field(default=0, init=False)
    total_signatures: int = field(default=0, init=False)

    def __post_init__(self):
        """Compute size and signature count from transactions."""
        if self.transactions:
            self.size_bytes = sum(tx.size_bytes for tx in self.transactions)
            self.total_signatures = sum(tx.num_signatures for tx in self.transactions)

    @property
    def tx_count(self) -> int:
        """Number of transactions in the block."""
        return len(self.transactions)

    def propagation_time_to_node(self, node_id: str) -> Optional[float]:
        """Time from proposal to first seen by a specific node."""
        if node_id not in self.first_seen_by:
            return None
        proposal_time = self.timestamp_ms
        return self.first_seen_by[node_id] - proposal_time

    def propagation_percentile(self, percentile: float) -> Optional[float]:
        """Time for block to reach given percentile of nodes.

        Args:
            percentile: Value between 0 and 100 (e.g., 90 for p90).

        Returns:
            Propagation time in ms, or None if insufficient data.
        """
        if not self.first_seen_by:
            return None

        # Get relative times from proposal
        proposal_time = self.timestamp_ms
        relative_times = sorted(
            t - proposal_time for t in self.first_seen_by.values()
        )

        if not relative_times:
            return None

        index = int(len(relative_times) * percentile / 100)
        return relative_times[min(index, len(relative_times) - 1)]

    def validation_percentile(self, percentile: float) -> Optional[float]:
        """Time for block to be validated by given percentile of nodes."""
        if not self.validated_by:
            return None

        proposal_time = self.timestamp_ms
        relative_times = sorted(
            t - proposal_time for t in self.validated_by.values()
        )

        if not relative_times:
            return None

        index = int(len(relative_times) * percentile / 100)
        return relative_times[min(index, len(relative_times) - 1)]

    def coverage(self, total_nodes: int) -> float:
        """Fraction of network that has seen this block."""
        if total_nodes <= 0:
            return 0.0
        return len(self.first_seen_by) / total_nodes

    def validation_coverage(self, total_nodes: int) -> float:
        """Fraction of network that has validated this block."""
        if total_nodes <= 0:
            return 0.0
        return len(self.validated_by) / total_nodes
