"""Tests for GlobalMempool."""

import pytest

from simulator.mempool.mempool import GlobalMempool, MempoolStats
from simulator.network.propagation import Transaction


def _make_tx(
    tx_id: str = "tx_0",
    size_bytes: int = 500,
    fee: int = 1000,
    algo: str = "Ed25519",
) -> Transaction:
    """Helper to create a Transaction with sensible defaults."""
    return Transaction(
        tx_id=tx_id,
        size_bytes=size_bytes,
        signature_algorithm=algo,
        num_signatures=1,
        fee_satoshis=fee,
        arrival_time_ms=0.0,
    )


class TestMempoolInit:
    """Constructor and validation tests."""

    def test_default_capacity(self):
        mp = GlobalMempool()
        assert mp.capacity_bytes == 100 * 1024 * 1024

    def test_custom_capacity(self):
        mp = GlobalMempool(capacity_bytes=1024)
        assert mp.capacity_bytes == 1024

    def test_zero_capacity_raises(self):
        with pytest.raises(ValueError, match="positive"):
            GlobalMempool(capacity_bytes=0)

    def test_negative_capacity_raises(self):
        with pytest.raises(ValueError, match="positive"):
            GlobalMempool(capacity_bytes=-100)


class TestAddTransaction:
    """Tests for add_transaction."""

    def test_accept_transaction(self):
        mp = GlobalMempool(capacity_bytes=10_000)
        tx = _make_tx(size_bytes=500)
        accepted, evicted = mp.add_transaction(tx)
        assert accepted is True
        assert evicted == []
        assert mp.tx_count == 1
        assert mp.size_bytes == 500

    def test_reject_oversized_transaction(self):
        mp = GlobalMempool(capacity_bytes=100)
        tx = _make_tx(size_bytes=200)
        accepted, evicted = mp.add_transaction(tx)
        assert accepted is False
        assert evicted == []
        assert mp.tx_count == 0

    def test_duplicate_ignored(self):
        mp = GlobalMempool(capacity_bytes=10_000)
        tx = _make_tx(tx_id="same", size_bytes=500)
        mp.add_transaction(tx)
        accepted, evicted = mp.add_transaction(tx)
        assert accepted is True
        assert evicted == []
        assert mp.tx_count == 1  # Still just one

    def test_eviction_under_pressure(self):
        """When mempool is full, lowest fee_rate gets evicted."""
        mp = GlobalMempool(capacity_bytes=1000)

        # Fill with a low-fee tx (500 bytes, 100 sat → fee_rate = 0.2)
        low = _make_tx(tx_id="low", size_bytes=500, fee=100)
        mp.add_transaction(low)

        # Add a high-fee tx that forces eviction (600 bytes, 6000 sat → fee_rate = 10)
        high = _make_tx(tx_id="high", size_bytes=600, fee=6000)
        accepted, evicted = mp.add_transaction(high)

        assert accepted is True
        assert len(evicted) == 1
        assert evicted[0].tx_id == "low"
        assert mp.tx_count == 1
        assert mp.contains("high")
        assert not mp.contains("low")

    def test_multiple_evictions(self):
        """May need to evict multiple txs for one large newcomer."""
        mp = GlobalMempool(capacity_bytes=1000)

        # Fill with 3 x 300-byte txs (900 bytes total)
        for i in range(3):
            mp.add_transaction(
                _make_tx(tx_id=f"small_{i}", size_bytes=300, fee=100 + i)
            )
        assert mp.tx_count == 3
        assert mp.size_bytes == 900

        # Insert a 400-byte tx → needs 400 bytes free → evict ~1-2 of the smallest
        big = _make_tx(tx_id="big", size_bytes=400, fee=5000)
        accepted, evicted = mp.add_transaction(big)
        assert accepted is True
        assert len(evicted) >= 1
        assert mp.contains("big")


class TestRemoveTransaction:
    """Tests for remove_transaction."""

    def test_remove_existing(self):
        mp = GlobalMempool(capacity_bytes=10_000)
        tx = _make_tx(tx_id="t1", size_bytes=500)
        mp.add_transaction(tx)
        removed = mp.remove_transaction("t1")
        assert removed is not None
        assert removed.tx_id == "t1"
        assert mp.tx_count == 0
        assert mp.size_bytes == 0

    def test_remove_nonexistent(self):
        mp = GlobalMempool(capacity_bytes=10_000)
        removed = mp.remove_transaction("nope")
        assert removed is None


class TestGetBlockCandidates:
    """Tests for get_block_candidates."""

    def test_selects_highest_fee_rate_first(self):
        mp = GlobalMempool(capacity_bytes=100_000)

        # Add 3 txs with different fee rates
        low = _make_tx(tx_id="low", size_bytes=500, fee=100)
        mid = _make_tx(tx_id="mid", size_bytes=500, fee=500)
        high = _make_tx(tx_id="high", size_bytes=500, fee=1000)
        mp.add_transaction(low)
        mp.add_transaction(mid)
        mp.add_transaction(high)

        candidates = mp.get_block_candidates(max_block_size_bytes=1200)
        # Should select highest fee_rate first
        assert candidates[0].tx_id == "high"
        assert candidates[1].tx_id == "mid"

    def test_respects_block_size_limit(self):
        mp = GlobalMempool(capacity_bytes=100_000)
        for i in range(100):
            mp.add_transaction(
                _make_tx(tx_id=f"t_{i}", size_bytes=500, fee=100 * (i + 1))
            )

        candidates = mp.get_block_candidates(max_block_size_bytes=2500)
        total_size = sum(c.size_bytes for c in candidates)
        assert total_size <= 2500

    def test_respects_max_txs(self):
        mp = GlobalMempool(capacity_bytes=100_000)
        for i in range(20):
            mp.add_transaction(
                _make_tx(tx_id=f"t_{i}", size_bytes=100, fee=100 * (i + 1))
            )

        candidates = mp.get_block_candidates(
            max_block_size_bytes=100_000, max_txs=5
        )
        assert len(candidates) <= 5

    def test_empty_mempool_returns_empty(self):
        mp = GlobalMempool(capacity_bytes=100_000)
        assert mp.get_block_candidates(max_block_size_bytes=10_000) == []


class TestMempoolStats:
    """Tests for stats() snapshot."""

    def test_stats_after_operations(self):
        mp = GlobalMempool(capacity_bytes=1000)
        mp.add_transaction(_make_tx(tx_id="a", size_bytes=400, fee=100))
        mp.add_transaction(_make_tx(tx_id="b", size_bytes=400, fee=200))
        # This forces eviction of 'a' (lowest fee_rate)
        mp.add_transaction(_make_tx(tx_id="c", size_bytes=400, fee=500))

        stats = mp.stats()
        assert stats.current_tx_count == 2
        assert stats.total_accepted == 3
        assert stats.total_evicted == 1
        assert stats.capacity_bytes == 1000


class TestMempoolUtilization:
    """Tests for utilization property."""

    def test_utilization_empty(self):
        mp = GlobalMempool(capacity_bytes=1000)
        assert mp.utilization == 0.0

    def test_utilization_partial(self):
        mp = GlobalMempool(capacity_bytes=1000)
        mp.add_transaction(_make_tx(size_bytes=500))
        assert mp.utilization == pytest.approx(0.5)

    def test_utilization_full(self):
        mp = GlobalMempool(capacity_bytes=500)
        mp.add_transaction(_make_tx(size_bytes=500))
        assert mp.utilization == pytest.approx(1.0)


class TestClear:
    """Tests for clear()."""

    def test_clear_empties_mempool(self):
        mp = GlobalMempool(capacity_bytes=10_000)
        for i in range(10):
            mp.add_transaction(_make_tx(tx_id=f"t_{i}", size_bytes=100))
        assert mp.tx_count == 10
        mp.clear()
        assert mp.tx_count == 0
        assert mp.size_bytes == 0
