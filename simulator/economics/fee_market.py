"""Dynamic fee market model for blockchain simulation.

Models how transaction fees respond to mempool backlog pressure,
enabling separate tracking of "economic failure" (priced-out txs)
vs "consensus failure" (blocks propagated too slowly / stale).

Three fee market models:
1. EIP-1559 (Ethereum): base fee adjusts up/down based on block fullness
2. First-price auction (Bitcoin): fee = market clearing rate
3. Priority fee (Solana): compute-unit pricing with priority tips

References:
    - EIP-1559: https://eips.ethereum.org/EIPS/eip-1559
    - Bitcoin fee estimation: https://bitcoinops.org/en/topics/fee-estimation/
    - Solana priority fees: https://solana.com/docs/core/fees
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class FeeMarketConfig:
    """Configuration for a dynamic fee market.

    Attributes:
        base_fee_floor: Minimum base fee (satoshis per byte).
        base_fee_ceiling: Maximum base fee.
        target_utilization: Target block utilization (0.5 = 50% full).
        adjustment_speed: Max fractional adjustment per block (EIP-1559: 0.125).
        fee_model: Fee market type: "eip1559", "first_price", or "priority_fee".
    """

    base_fee_floor: float = 1.0
    base_fee_ceiling: float = 10_000.0
    target_utilization: float = 0.5
    adjustment_speed: float = 0.125
    fee_model: str = "eip1559"


# Chain-specific fee market presets
FEE_MARKET_PRESETS = {
    "solana": FeeMarketConfig(
        base_fee_floor=0.5,
        base_fee_ceiling=5000.0,
        target_utilization=0.5,
        adjustment_speed=0.10,
        fee_model="priority_fee",
    ),
    "ethereum": FeeMarketConfig(
        base_fee_floor=1.0,
        base_fee_ceiling=10_000.0,
        target_utilization=0.5,
        adjustment_speed=0.125,  # EIP-1559: 12.5%
        fee_model="eip1559",
    ),
    "bitcoin": FeeMarketConfig(
        base_fee_floor=1.0,
        base_fee_ceiling=50_000.0,
        target_utilization=0.5,
        adjustment_speed=0.20,
        fee_model="first_price",
    ),
}


class DynamicFeeMarket:
    """Tracks mempool backlog and adjusts the effective minimum fee.

    The fee market creates economic pressure on transactions:
    - When blocks are full → fees rise → small-fee txs are priced out
    - When blocks are empty → fees fall → more txs can afford inclusion
    - PQC transactions are larger → need higher absolute fees for same fee_rate

    This separates two types of failure:
    1. Economic failure: tx priced out (fee < base_fee × size)
    2. Consensus failure: block propagates too slowly (stale)
    """

    def __init__(self, config: FeeMarketConfig, rng: Optional[random.Random] = None):
        """Initialize fee market.

        Args:
            config: Fee market configuration.
            rng: Random number generator for fee sampling.
        """
        self.config = config
        self.rng = rng or random.Random(42)

        # Current base fee (starts at floor)
        self.base_fee: float = config.base_fee_floor

        # History tracking
        self._base_fee_history: List[Tuple[float, float]] = []  # (time_ms, base_fee)
        self._fees_paid: List[float] = []
        self._economic_rejections: int = 0
        self._total_fee_checks: int = 0
        self._last_block_fees: List[float] = []

    def update_base_fee(
        self,
        current_time_ms: float,
        mempool_utilization: float,
        block_utilization: float = 1.0,
    ) -> None:
        """Adjust base fee after a block is produced.

        Args:
            current_time_ms: Current simulation time.
            mempool_utilization: Fraction of mempool capacity in use (0-1).
            block_utilization: Fraction of block capacity used (0-1).
        """
        self._base_fee_history.append((current_time_ms, self.base_fee))

        if self.config.fee_model == "eip1559":
            self._update_eip1559(block_utilization)
        elif self.config.fee_model == "first_price":
            self._update_first_price()
        elif self.config.fee_model == "priority_fee":
            self._update_priority_fee(mempool_utilization, block_utilization)
        else:
            self._update_eip1559(block_utilization)

        # Clamp to bounds
        self.base_fee = max(self.config.base_fee_floor,
                            min(self.config.base_fee_ceiling, self.base_fee))

        # Reset last block fees
        self._last_block_fees = []

    def _update_eip1559(self, block_utilization: float) -> None:
        """EIP-1559 style: fee adjusts based on block fullness vs target.

        If block is more full than target → fee increases
        If block is less full than target → fee decreases
        Maximum change per block: adjustment_speed fraction.
        """
        target = self.config.target_utilization
        if target <= 0:
            return

        # Change proportional to deviation from target
        delta = (block_utilization - target) / target
        # Clamp delta to [-1, 1]
        delta = max(-1.0, min(1.0, delta))
        adjustment = 1.0 + self.config.adjustment_speed * delta
        self.base_fee *= adjustment

    def _update_first_price(self) -> None:
        """Bitcoin first-price auction: base fee = min fee in last block.

        If no fees recorded, fee decays slightly (incentivizes submission).
        """
        if self._last_block_fees:
            # Market clearing price: lowest fee included in block
            self.base_fee = min(self._last_block_fees)
        else:
            # Decay toward floor
            self.base_fee *= 0.95

    def _update_priority_fee(
        self,
        mempool_utilization: float,
        block_utilization: float = 1.0,
    ) -> None:
        """Solana priority fee: adjusts based on BLOCK pressure (primary) and
        mempool pressure (secondary).

        Previous implementation used only mempool_utilization, but the Solana
        mempool (100 MB) and block (6 MB) are on very different scales.  With a
        barely-used 100 MB mempool, mempool_utilization ≈ 0, yet every block may
        be full.  Using only mempool_utilization caused fees to DECAY when blocks
        were full — the opposite of intended behaviour.

        Fix: use block_utilization as the primary pressure signal (matching
        EIP-1559's approach).  Mempool pressure provides a secondary signal for
        sustained demand that has not yet been included in blocks.
        """
        target = self.config.target_utilization
        if target <= 0:
            return

        # Block pressure is the primary signal
        block_pressure = block_utilization / target
        # Mempool pressure is a secondary signal (dampened by 0.3×)
        mempool_pressure = (mempool_utilization / target) * 0.3
        # Combined pressure: weighted blend
        pressure = max(block_pressure, mempool_pressure)

        if pressure > 1.0:
            # Over-pressure → fee increases
            self.base_fee *= (1.0 + self.config.adjustment_speed * min(pressure - 1.0, 2.0))
        else:
            # Under-pressure → fee decreases
            self.base_fee *= (1.0 - self.config.adjustment_speed * (1.0 - pressure) * 0.5)

    def generate_tx_fee(self, tx_size_bytes: int, is_pqc: bool = False) -> int:
        """Generate a realistic fee for a new transaction.

        Draws from a lognormal distribution centered above the base fee.
        The fee is in absolute terms (satoshis), not per-byte.

        Args:
            tx_size_bytes: Transaction size in bytes (for fee_rate calculation).
            is_pqc: Whether this is a PQC transaction (may need higher absolute fee).

        Returns:
            Fee in satoshis (or equivalent unit).
        """
        # Target fee_rate is above base_fee
        target_rate = self.base_fee * (1.2 if not is_pqc else 1.5)

        # Draw from lognormal
        mu = math.log(max(target_rate, 0.01))
        sigma = 0.5  # Moderate variance

        fee_rate = self.rng.lognormvariate(mu, sigma)
        fee_rate = max(fee_rate, self.config.base_fee_floor * 0.5)  # Allow some below base

        absolute_fee = int(fee_rate * tx_size_bytes)
        return max(1, absolute_fee)

    def check_acceptable(self, fee_satoshis: int, tx_size_bytes: int) -> bool:
        """Check if a transaction's fee meets the minimum threshold.

        Args:
            fee_satoshis: Transaction fee.
            tx_size_bytes: Transaction size in bytes.

        Returns:
            True if acceptable, False if economic failure.
        """
        self._total_fee_checks += 1
        if tx_size_bytes <= 0:
            return True

        fee_rate = fee_satoshis / tx_size_bytes
        if fee_rate < self.base_fee:
            self._economic_rejections += 1
            return False

        return True

    def record_block_fee(self, fee_rate: float) -> None:
        """Record a fee rate included in a block (for first-price model).

        Args:
            fee_rate: Fee rate (satoshis/byte) of an included transaction.
        """
        self._last_block_fees.append(fee_rate)
        self._fees_paid.append(fee_rate)

    def min_acceptable_fee_rate(self) -> float:
        """Current minimum acceptable fee rate (satoshis/byte)."""
        return self.base_fee

    def metrics(self) -> dict:
        """Return fee market metrics for results aggregation.

        Returns:
            Dictionary with fee market statistics.
        """
        fees = self._fees_paid
        history = [bf for _, bf in self._base_fee_history]

        return {
            "fee_market_enabled": True,
            "base_fee_mean": sum(history) / len(history) if history else 0.0,
            "base_fee_final": self.base_fee,
            "base_fee_max": max(history) if history else 0.0,
            "base_fee_min": min(history) if history else 0.0,
            "economic_failure_count": self._economic_rejections,
            "economic_failure_rate": (
                self._economic_rejections / self._total_fee_checks
                if self._total_fee_checks > 0
                else 0.0
            ),
            "avg_fee_paid": sum(fees) / len(fees) if fees else 0.0,
            "median_fee_paid": (
                sorted(fees)[len(fees) // 2] if len(fees) % 2 == 1
                else (sorted(fees)[len(fees)//2 - 1] + sorted(fees)[len(fees)//2]) / 2.0
            ) if fees else 0.0,
            "total_fee_checks": self._total_fee_checks,
        }
