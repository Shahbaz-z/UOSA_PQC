"""Simulation state management for the DES engine."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from simulator.core.events import Event, EventType

if TYPE_CHECKING:
    from simulator.network.propagation import Block


@dataclass
class SimulationState:
    """Complete state of the discrete event simulation.

    Manages the event queue, block tracking, and chain state.
    All times are in milliseconds.
    """

    # Time management
    current_time_ms: float = 0.0
    end_time_ms: float = 60_000.0  # Default: 1 minute

    # Event queue (min-heap by time, then priority, then sequence)
    event_queue: List[Event] = field(default_factory=list)
    event_counter: int = 0  # Unique sequence for deterministic ordering

    # Completed events (for post-simulation analysis)
    completed_events: List[Event] = field(default_factory=list)

    # Block tracking
    blocks_proposed: List["Block"] = field(default_factory=list)
    blocks_finalized: List["Block"] = field(default_factory=list)
    orphaned_blocks: List["Block"] = field(default_factory=list)

    # O(1) block lookup by hash.  Populated in register_block().
    # Without this, get_block_by_hash does an O(n) linear scan on every
    # BLOCK_RECEIVED and BLOCK_PROPAGATED event.  For a 5-minute Solana
    # simulation (~750 blocks × 75 nodes × 150 events/block ≈ 8M calls)
    # the scan cost grows super-linearly.  The dict adds negligible memory.
    _block_index: Dict[str, "Block"] = field(default_factory=dict)

    # Chain state (simplified: linear chain, no forks modeled yet)
    chain_tip_hash: str = "genesis"
    chain_height: int = 0

    # Metrics accumulators
    total_bytes_transmitted: int = 0
    total_verifications: int = 0

    def schedule_event(
        self,
        time_ms: float,
        event_type: EventType,
        payload: Dict[str, Any],
    ) -> None:
        """Schedule an event on the priority queue.

        Events are automatically assigned a sequence number for
        deterministic ordering of same-time events.
        """
        self.event_counter += 1
        event = Event.create(
            time_ms=time_ms,
            event_type=event_type,
            payload=payload,
            sequence=self.event_counter,
        )
        heapq.heappush(self.event_queue, event)

    def pop_next_event(self) -> Optional[Event]:
        """Pop the next event from the queue (lowest time/priority)."""
        if not self.event_queue:
            return None
        return heapq.heappop(self.event_queue)

    def peek_next_event(self) -> Optional[Event]:
        """Peek at the next event without removing it."""
        if not self.event_queue:
            return None
        return self.event_queue[0]

    def has_events(self) -> bool:
        """Check if there are pending events."""
        return len(self.event_queue) > 0

    def get_block_by_hash(self, block_hash: str) -> Optional["Block"]:
        """O(1) block lookup by hash via the _block_index dict.

        Previous implementation did an O(n) linear scan of blocks_proposed
        which was called on every BLOCK_RECEIVED and BLOCK_PROPAGATED event.
        """
        return self._block_index.get(block_hash)

    def register_block(self, block: "Block") -> None:
        """Register a newly proposed block."""
        self.blocks_proposed.append(block)
        self._block_index[block.block_hash] = block  # O(1) index update
        self.chain_height = block.height
        self.chain_tip_hash = block.block_hash
