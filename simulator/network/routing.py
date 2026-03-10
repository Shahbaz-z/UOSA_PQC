"""Chain-specific routing strategies for block propagation.

Models the distinct ways different blockchains propagate blocks:
- Solana: Turbine tree-structured shred distribution
- Bitcoin: Compact block relay (BIP 152)
- Ethereum: Hybrid direct-propagation + block-announcement

Each strategy determines which peers receive the block and in what order,
which directly affects propagation latency and NIC utilization patterns.
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from simulator.network.node import Node
    from simulator.network.propagation import Block


@dataclass
class PropagationTask:
    """A single send from one node to another.

    Attributes:
        sender_id: Node sending the block/data.
        receiver_id: Node receiving.
        size_bytes: Actual bytes transmitted over the wire.
        layer: Routing layer (0 = direct from leader, 1+ = relayed).
        is_compact: Whether this is a compact/announcement (smaller than full block).
    """
    sender_id: str
    receiver_id: str
    size_bytes: int
    layer: int = 0
    is_compact: bool = False


class RoutingStrategy(ABC):
    """Abstract routing strategy for block propagation."""

    @abstractmethod
    def plan_propagation(
        self,
        sender: "Node",
        block: "Block",
        all_nodes: Dict[str, "Node"],
        already_seen: set,
        rng: random.Random,
    ) -> List[PropagationTask]:
        """Plan how a sender propagates a block to the network.

        Called when a node has a validated block and wants to forward it.
        Returns a list of PropagationTasks describing each send.

        Args:
            sender: Node initiating this round of propagation.
            block: Block being propagated.
            all_nodes: All nodes in the network.
            already_seen: Set of node_ids that already have the block.
            rng: Random number generator for reproducibility.

        Returns:
            List of PropagationTask objects.
        """
        ...


class GossipRouting(RoutingStrategy):
    """Simple random gossip — the original/fallback model.

    Each node forwards to `fanout` random peers that haven't seen the block.
    Used as baseline and for chains without a specific model.
    """

    def __init__(self, fanout: int = 8):
        self.fanout = fanout

    def plan_propagation(
        self,
        sender: "Node",
        block: "Block",
        all_nodes: Dict[str, "Node"],
        already_seen: set,
        rng: random.Random,
    ) -> List[PropagationTask]:
        available = [
            n for nid, n in all_nodes.items()
            if nid != sender.node_id and nid not in already_seen
        ]
        if not available:
            return []

        k = min(self.fanout, len(available))
        peers = rng.sample(available, k)

        return [
            PropagationTask(
                sender_id=sender.node_id,
                receiver_id=p.node_id,
                size_bytes=block.size_bytes,
                layer=0,
                is_compact=False,
            )
            for p in peers
        ]


class TurbineRouting(RoutingStrategy):
    """Solana Turbine-like tree-structured propagation.

    The leader distributes to a first layer of nodes (layer 0),
    each layer-0 node relays to a set of layer-1 nodes, and so on.
    This creates a structured tree rather than random gossip.

    Key parameters:
        fanout: How many peers each node in a layer sends to.
        num_layers: Derived from ceil(log_fanout(num_nodes)).

    The trade-off vs random gossip:
    - Fewer total messages (each node sends to at most `fanout` peers)
    - Deterministic coverage (every node gets assigned a layer)
    - BUT sequential layer delays: layer N only starts after layer N-1

    For the DES engine, we return all tasks at once and let the engine
    compute delays. The layer information allows the engine to add
    sequential layer delays.
    """

    def __init__(self, fanout: int = 200):
        self.fanout = fanout

    def plan_propagation(
        self,
        sender: "Node",
        block: "Block",
        all_nodes: Dict[str, "Node"],
        already_seen: set,
        rng: random.Random,
    ) -> List[PropagationTask]:
        # Only the block proposer does Turbine tree assignment.
        # Relay nodes (non-proposers) just forward to their assigned children.
        # For simplicity in the DES, we plan the full tree from the sender's
        # perspective: the sender picks `fanout` layer-0 nodes.
        available = [
            n for nid, n in all_nodes.items()
            if nid != sender.node_id and nid not in already_seen
        ]
        if not available:
            return []

        rng.shuffle(available)

        k = min(self.fanout, len(available))
        layer_0 = available[:k]

        return [
            PropagationTask(
                sender_id=sender.node_id,
                receiver_id=p.node_id,
                size_bytes=block.size_bytes,
                layer=0,
                is_compact=False,
            )
            for p in layer_0
        ]


class CompactBlockRouting(RoutingStrategy):
    """Bitcoin compact block relay (BIP 152).

    First `fanout` peers receive the full block. When those peers relay,
    they send compact blocks (header + short transaction IDs) which are
    ~10% of the full block size. Receiving nodes that already have the
    transactions in their mempool can reconstruct the full block.

    This significantly reduces bandwidth for relay hops, making Bitcoin
    more resilient to PQC signature size inflation during propagation.
    """

    def __init__(self, fanout: int = 8, compact_fraction: float = 0.10):
        self.fanout = fanout
        self.compact_fraction = compact_fraction

    def plan_propagation(
        self,
        sender: "Node",
        block: "Block",
        all_nodes: Dict[str, "Node"],
        already_seen: set,
        rng: random.Random,
    ) -> List[PropagationTask]:
        available = [
            n for nid, n in all_nodes.items()
            if nid != sender.node_id and nid not in already_seen
        ]
        if not available:
            return []

        k = min(self.fanout, len(available))
        peers = rng.sample(available, k)

        # Determine if sender is the original proposer or a relay
        is_relay = sender.node_id != block.proposer_id

        tasks = []
        for p in peers:
            if is_relay:
                # Relay: send compact block
                size = max(1, int(block.size_bytes * self.compact_fraction))
                is_compact = True
            else:
                # Proposer: send full block to first peers
                size = block.size_bytes
                is_compact = False

            tasks.append(PropagationTask(
                sender_id=sender.node_id,
                receiver_id=p.node_id,
                size_bytes=size,
                layer=0,
                is_compact=is_compact,
            ))

        return tasks


class EthHybridRouting(RoutingStrategy):
    """Ethereum hybrid propagation model.

    Ethereum uses two parallel mechanisms:
    1. Direct block propagation to sqrt(num_peers) peers (full block)
    2. Block-hash announcement to remaining peers (tiny message)
       - Peers that don't have the block then request it

    The announcement message is very small (~100 bytes: hash + number).
    The full-block direct propagation to sqrt(N) peers provides fast
    initial spread, while announcements ensure coverage.
    """

    ANNOUNCEMENT_SIZE_BYTES = 100  # block hash + block number

    def __init__(self, fanout: int = 16):
        """fanout here is the total peer count (not direct-send count)."""
        self.fanout = fanout

    def plan_propagation(
        self,
        sender: "Node",
        block: "Block",
        all_nodes: Dict[str, "Node"],
        already_seen: set,
        rng: random.Random,
    ) -> List[PropagationTask]:
        available = [
            n for nid, n in all_nodes.items()
            if nid != sender.node_id and nid not in already_seen
        ]
        if not available:
            return []

        k = min(self.fanout, len(available))
        peers = rng.sample(available, k)

        # sqrt(peers) get direct full block
        num_direct = max(1, int(math.sqrt(k)))
        direct_peers = peers[:num_direct]
        announce_peers = peers[num_direct:]

        tasks = []
        # Direct propagation: full block
        for p in direct_peers:
            tasks.append(PropagationTask(
                sender_id=sender.node_id,
                receiver_id=p.node_id,
                size_bytes=block.size_bytes,
                layer=0,
                is_compact=False,
            ))

        # Announcement: tiny message, then they request full block
        # Model as: announcement delay + full block download
        # For simplicity: the size_bytes is the full block (they'll request it)
        # but mark as compact so the engine knows the initial send is small
        for p in announce_peers:
            tasks.append(PropagationTask(
                sender_id=sender.node_id,
                receiver_id=p.node_id,
                size_bytes=self.ANNOUNCEMENT_SIZE_BYTES,
                layer=0,
                is_compact=True,
            ))

        return tasks


def get_routing_strategy(chain: str) -> RoutingStrategy:
    """Get the appropriate routing strategy for a chain.

    Args:
        chain: Chain name (case-insensitive).

    Returns:
        RoutingStrategy instance configured for the chain.
    """
    chain_lower = chain.lower()
    if chain_lower == "solana":
        return TurbineRouting(fanout=200)
    elif chain_lower == "bitcoin":
        return CompactBlockRouting(fanout=8, compact_fraction=0.10)
    elif chain_lower == "ethereum":
        return EthHybridRouting(fanout=16)
    else:
        # Default: basic gossip
        return GossipRouting(fanout=8)
