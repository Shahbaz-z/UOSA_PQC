"""Phase 3: Global Mempool with bounded capacity and fee-rate eviction.

Implements a bounded mempool that enforces a strict lowest-fee-rate-per-byte
eviction policy. When the mempool exceeds its capacity, transactions with
the lowest fee_rate (satoshis/byte) are evicted first.

This creates the economic feedback loop where bloated PQC transactions
crowd out cheaper classical transactions — or pay more to survive.

Performance design:
  - _txs: Dict[str, Transaction]   — O(1) lookup / removal by tx_id
  - _eviction_heap: min-heap        — O(log n) eviction of lowest-fee-rate tx

The heap stores (priority, tx_id) tuples.  When a transaction is removed
from _txs (by block inclusion), a corresponding "dead" entry remains in the
heap; _evict_lowest_fee_rate() skips these lazily (lazy deletion pattern).

Previous implementation used min() scan for eviction: O(n) per eviction,
which is acceptable at the simulated scale (<10,000 txs) but degrades
super-linearly under high-throughput Monte Carlo sweeps.  The heapq upgrade
reduces eviction to O(log n) with O(n) space overhead for dead entries.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulator.network.propagation import Transaction


@dataclass
class MempoolStats:
    """Snapshot of mempool state for metrics collection."""
    current_size_bytes: int = 0
    current_tx_count: int = 0
    total_accepted: int = 0
    total_evicted: int = 0
    # total_rejected: combined count (tx > capacity AND post-eviction no-room).
    # These are two distinct rejection causes; tracked together for simplicity
    # since both represent demand that could not be served.
    total_rejected: int = 0
    capacity_bytes: int = 0


class GlobalMempool:
    """Bounded mempool with O(log n) lowest-fee-rate eviction.

    Transactions are stored in a dict for O(1) lookup;
    a heapq-backed min-heap enables O(log n) eviction of the
    lowest-fee-rate transaction.

    Capacity is enforced in bytes, matching real-world mempool limits.

    Args:
        capacity_bytes: Maximum mempool size in bytes (default 100 MB).
    """

    def __init__(self, capacity_bytes: int = 100 * 1024 * 1024) -> None:
        if capacity_bytes <= 0:
            raise ValueError(
                f"capacity_bytes must be positive, got {capacity_bytes}"
            )
        self.capacity_bytes = capacity_bytes
        self._txs: Dict[str, Transaction] = {}   # tx_id → Transaction
        self._current_size_bytes: int = 0

        # Min-heap of (priority, tx_id) for O(log n) eviction.
        # Uses lazy deletion: entries for removed transactions are left in the
        # heap and skipped on pop (checked against _txs for liveness).
        self._eviction_heap: List[Tuple[float, str]] = []

        # Eviction tracking
        self._total_accepted: int = 0
        self._total_evicted: int = 0
        self._total_rejected: int = 0

    @property
    def size_bytes(self) -> int:
        return self._current_size_bytes

    @property
    def tx_count(self) -> int:
        return len(self._txs)

    @property
    def utilization(self) -> float:
        """Current utilization as a fraction of capacity."""
        if self.capacity_bytes == 0:
            return 0.0
        return self._current_size_bytes / self.capacity_bytes

    def add_transaction(self, tx: Transaction) -> Tuple[bool, List[Transaction]]:
        """Add a transaction to the mempool, evicting as needed.

        Args:
            tx: Transaction to add.

        Returns:
            Tuple of (accepted: bool, evicted: list of evicted transactions).
            If the transaction itself is larger than capacity, it is rejected
            and accepted=False with no evictions.
        """
        # Reject transactions larger than total capacity
        if tx.size_bytes > self.capacity_bytes:
            self._total_rejected += 1
            return False, []

        # Already in mempool
        if tx.tx_id in self._txs:
            return True, []

        evicted: List[Transaction] = []

        # Evict lowest-fee-rate transactions until there's room
        while (self._current_size_bytes + tx.size_bytes > self.capacity_bytes
               and self._txs):
            victim = self._evict_lowest_fee_rate()
            if victim is not None:
                evicted.append(victim)
            else:
                break  # Safety: shouldn't happen if _txs is non-empty

        # Final check: if still no room after evicting everything, reject
        if self._current_size_bytes + tx.size_bytes > self.capacity_bytes:
            self._total_rejected += 1
            return False, evicted

        # Accept the transaction
        self._txs[tx.tx_id] = tx
        self._current_size_bytes += tx.size_bytes
        self._total_accepted += 1
        # Push to eviction heap (min priority = first to be evicted)
        heapq.heappush(self._eviction_heap, (tx.priority, tx.tx_id))

        return True, evicted

    def remove_transaction(self, tx_id: str) -> Optional[Transaction]:
        """Remove a transaction (e.g., included in a block).

        The corresponding heap entry is NOT removed eagerly; it will be
        skipped lazily next time _evict_lowest_fee_rate() is called.

        Returns:
            The removed transaction, or None if not found.
        """
        tx = self._txs.pop(tx_id, None)
        if tx is not None:
            self._current_size_bytes -= tx.size_bytes
        return tx

    def get_block_candidates(
        self,
        max_block_size_bytes: int,
        max_txs: int = 10_000,
    ) -> List[Transaction]:
        """Select highest-fee-rate transactions for block inclusion.

        Greedy selection: pick transactions in descending fee_rate order
        until the block is full.

        Args:
            max_block_size_bytes: Maximum block size in bytes.
            max_txs: Maximum number of transactions in a block.

        Returns:
            List of transactions selected for the block.
        """
        # Sort by fee_rate descending (highest priority first)
        sorted_txs = sorted(
            self._txs.values(),
            key=lambda t: t.priority,
            reverse=True,
        )

        selected: List[Transaction] = []
        total_size = 0

        for tx in sorted_txs:
            if len(selected) >= max_txs:
                break
            if total_size + tx.size_bytes > max_block_size_bytes:
                continue  # Skip this tx, try smaller ones
            selected.append(tx)
            total_size += tx.size_bytes

        return selected

    def _evict_lowest_fee_rate(self) -> Optional[Transaction]:
        """Evict the transaction with the lowest fee rate in O(log n).

        Uses lazy deletion: heap entries for transactions already removed from
        _txs (by block inclusion or prior eviction) are skipped on pop.

        Returns:
            The evicted transaction, or None if mempool is empty.
        """
        while self._eviction_heap:
            priority, tx_id = heapq.heappop(self._eviction_heap)
            # Check if this entry is still live (not lazily deleted)
            if tx_id not in self._txs:
                continue  # Dead entry — skip it
            # Live entry: evict
            victim = self._txs.pop(tx_id)
            self._current_size_bytes -= victim.size_bytes
            self._total_evicted += 1
            return victim

        return None  # Heap empty — nothing to evict

    def stats(self) -> MempoolStats:
        """Return current mempool statistics."""
        return MempoolStats(
            current_size_bytes=self._current_size_bytes,
            current_tx_count=len(self._txs),
            total_accepted=self._total_accepted,
            total_evicted=self._total_evicted,
            total_rejected=self._total_rejected,
            capacity_bytes=self.capacity_bytes,
        )

    def contains(self, tx_id: str) -> bool:
        return tx_id in self._txs

    def clear(self) -> None:
        """Clear the mempool."""
        self._txs.clear()
        self._current_size_bytes = 0
        self._eviction_heap.clear()
