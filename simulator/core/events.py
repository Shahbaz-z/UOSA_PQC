"""Event types and Event dataclass for the DES engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict


class EventType(Enum):
    """DES event types for network simulation.

    Event priority (lower = processed first when times are equal):
    1. SLOT_TICK - Time boundaries (highest priority)
    2. BLOCK_PROPOSED - Block creation
    3. BLOCK_PROPAGATED - Gossip initiation
    4. BLOCK_RECEIVED - Block arrival at peer
    5. BLOCK_VALIDATED - Verification complete
    6. TX_ARRIVED - Transaction mempool arrival (Phase 2)
    7. SIMULATION_END - Termination
    """
    SLOT_TICK = auto()
    BLOCK_PROPOSED = auto()
    BLOCK_PROPAGATED = auto()
    BLOCK_RECEIVED = auto()
    BLOCK_VALIDATED = auto()
    TX_ARRIVED = auto()
    SIMULATION_END = auto()


# Event priority mapping (lower = higher priority)
EVENT_PRIORITIES: Dict[EventType, int] = {
    EventType.SLOT_TICK: 1,
    EventType.BLOCK_PROPOSED: 2,
    EventType.BLOCK_PROPAGATED: 5,
    EventType.BLOCK_RECEIVED: 10,
    EventType.BLOCK_VALIDATED: 15,
    EventType.TX_ARRIVED: 20,
    EventType.SIMULATION_END: 100,
}


@dataclass(order=True)
class Event:
    """A scheduled event in the DES priority queue.

    Events are ordered by:
    1. time_ms (ascending - earlier events first)
    2. priority (ascending - lower number = higher priority)
    3. sequence (ascending - FIFO for same time/priority)

    The payload is not included in comparison to avoid type errors.
    """
    time_ms: float
    priority: int = field(compare=True)
    event_type: EventType = field(compare=False)
    payload: Dict[str, Any] = field(compare=False, default_factory=dict)
    sequence: int = field(default=0, compare=True)

    @classmethod
    def create(
        cls,
        time_ms: float,
        event_type: EventType,
        payload: Dict[str, Any],
        sequence: int = 0,
    ) -> "Event":
        """Factory method with automatic priority assignment."""
        priority = EVENT_PRIORITIES.get(event_type, 50)
        return cls(
            time_ms=time_ms,
            priority=priority,
            event_type=event_type,
            payload=payload,
            sequence=sequence,
        )
