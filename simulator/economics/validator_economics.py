"""Validator economics model: profitability, break-even, and exit dynamics.

Models the key economic equation for proof-of-stake validators:
    Revenue = R × (1 - s)
    Profit  = R × (1 - s) - c

Where:
    R = block reward per slot (if selected as proposer)
    s = stale rate (probability the block is wasted)
    c = operating cost per slot (hardware + bandwidth + vote costs)

When profit goes negative, validators begin exiting the network.
The exit probability follows a sigmoid centered on the break-even
stale rate, with heterogeneous cost structures (some validators
are more marginal than others).

References:
    - Solana validator economics: https://solana.com/staking
    - Ethereum validator economics: https://ethereum.org/en/staking/
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ValidatorEconomicsConfig:
    """Per-chain validator cost structure.

    All monetary values in USD for cross-chain comparability.

    Attributes:
        block_reward_per_slot_usd: Average revenue per slot if selected.
        vote_cost_per_slot_usd: Vote transaction cost per slot (Solana-specific).
        hardware_monthly_usd: Monthly server/hardware cost.
        bandwidth_monthly_usd: Monthly bandwidth cost.
        slots_per_month: Total slots in a month (for amortizing fixed costs).
        chain: Chain identifier.
    """

    block_reward_per_slot_usd: float = 0.05
    vote_cost_per_slot_usd: float = 0.01
    hardware_monthly_usd: float = 1500.0
    bandwidth_monthly_usd: float = 200.0
    slots_per_month: float = 6_480_000.0   # 400ms slots × 30 days
    chain: str = "solana"

    @property
    def cost_per_slot_usd(self) -> float:
        """Total cost per slot (fixed + variable)."""
        monthly_fixed = self.hardware_monthly_usd + self.bandwidth_monthly_usd
        fixed_per_slot = monthly_fixed / self.slots_per_month if self.slots_per_month > 0 else 0
        return fixed_per_slot + self.vote_cost_per_slot_usd


# Chain-specific presets with realistic 2025 cost structures
VALIDATOR_PRESETS = {
    "solana": ValidatorEconomicsConfig(
        block_reward_per_slot_usd=0.05,     # ~$0.05/slot average (staking rewards + fees)
        vote_cost_per_slot_usd=0.008,       # ~$0.008/vote tx
        hardware_monthly_usd=1500.0,        # Bare metal: 256GB RAM, high-IOPS SSD
        bandwidth_monthly_usd=200.0,        # 1 Gbps dedicated
        slots_per_month=6_480_000.0,        # 400ms × 86400 × 30
        chain="solana",
    ),
    "ethereum": ValidatorEconomicsConfig(
        block_reward_per_slot_usd=0.08,     # ~0.04 ETH × ~$2000 / slots
        vote_cost_per_slot_usd=0.0,         # Attestations are free
        hardware_monthly_usd=100.0,         # Much lower requirements
        bandwidth_monthly_usd=50.0,
        slots_per_month=216_000.0,          # 12s slots × 86400 × 30
        chain="ethereum",
    ),
    "bitcoin": ValidatorEconomicsConfig(
        block_reward_per_slot_usd=0.0,      # Full nodes receive no block reward
        vote_cost_per_slot_usd=0.0,
        hardware_monthly_usd=50.0,
        bandwidth_monthly_usd=30.0,
        slots_per_month=4_320.0,            # 10min × 30 days
        chain="bitcoin",
    ),
}


class ValidatorEconomicsModel:
    """Maps stale rate to profitability and network exit dynamics.

    Computes whether validators are profitable at a given stale rate,
    and estimates the probability that marginal validators exit.
    """

    def __init__(
        self,
        config: ValidatorEconomicsConfig,
        exit_steepness: float = 20.0,
        marginal_fraction: float = 0.20,
        marginal_cost_multiplier: float = 1.5,
    ):
        """Initialize economics model.

        Args:
            config: Validator cost structure.
            exit_steepness: Sigmoid steepness for exit probability.
            marginal_fraction: Fraction of validators that are marginal (high-cost).
            marginal_cost_multiplier: Cost multiplier for marginal validators.
        """
        self.config = config
        self._exit_steepness = exit_steepness
        self._marginal_fraction = marginal_fraction
        self._marginal_cost_multiplier = marginal_cost_multiplier

    def break_even_stale_rate(self) -> float:
        """Maximum stale rate where R(1-s) >= c.

        Solve: R(1-s) = c → s = 1 - c/R

        Returns:
            Break-even stale rate (0 to 1). Returns 1.0 if R=0
            (Bitcoin full nodes have no reward, run as public good).
        """
        R = self.config.block_reward_per_slot_usd
        c = self.config.cost_per_slot_usd
        if R <= 0:
            return 1.0  # No reward → break-even undefined, always running
        s_max = 1.0 - c / R
        return max(0.0, min(1.0, s_max))

    def profit_margin(self, stale_rate: float) -> float:
        """Net profit margin at a given stale rate.

        margin = (R(1-s) - c) / R
        Positive = profitable, Negative = losing money.

        Args:
            stale_rate: Fraction of blocks that go stale (0 to 1).

        Returns:
            Profit margin (-1 to 1). Returns -1.0 if R=0.
        """
        R = self.config.block_reward_per_slot_usd
        c = self.config.cost_per_slot_usd
        if R <= 0:
            return -1.0
        return (R * (1 - stale_rate) - c) / R

    def exit_probability(self, stale_rate: float) -> float:
        """Probability a marginal validator exits.

        Uses sigmoid: p_exit = 1 / (1 + exp(-k × (s - s_breakeven)))

        This gives a smooth transition:
        - Far below break-even: ~0% exit
        - At break-even: 50% exit
        - Far above break-even: ~100% exit

        Args:
            stale_rate: Current stale rate.

        Returns:
            Exit probability (0 to 1).
        """
        s_be = self.break_even_stale_rate()
        k = self._exit_steepness
        x = k * (stale_rate - s_be)
        # Clamp to avoid overflow
        x = max(-500.0, min(500.0, x))
        return 1.0 / (1.0 + math.exp(-x))

    def network_shrinkage(
        self, stale_rate: float, num_validators: int
    ) -> Tuple[int, float]:
        """Estimate the number of validators that exit.

        Not all validators are identical. Models heterogeneous cost
        structures: marginal validators (highest cost, lowest stake)
        exit first.

        Args:
            stale_rate: Current stale rate.
            num_validators: Current validator count.

        Returns:
            Tuple of (num_exits, remaining_fraction).
        """
        # Compute exit probability for base-cost validators
        base_p_exit = self.exit_probability(stale_rate)

        # Marginal validators have higher costs → lower break-even
        marginal_config = ValidatorEconomicsConfig(
            block_reward_per_slot_usd=self.config.block_reward_per_slot_usd,
            vote_cost_per_slot_usd=self.config.vote_cost_per_slot_usd * self._marginal_cost_multiplier,
            hardware_monthly_usd=self.config.hardware_monthly_usd * self._marginal_cost_multiplier,
            bandwidth_monthly_usd=self.config.bandwidth_monthly_usd * self._marginal_cost_multiplier,
            slots_per_month=self.config.slots_per_month,
            chain=self.config.chain,
        )
        marginal_model = ValidatorEconomicsModel(
            marginal_config,
            exit_steepness=self._exit_steepness,
        )
        marginal_p_exit = marginal_model.exit_probability(stale_rate)

        # Weighted average exit rate
        n_marginal = int(num_validators * self._marginal_fraction)
        n_base = num_validators - n_marginal

        expected_exits = n_base * base_p_exit + n_marginal * marginal_p_exit
        actual_exits = min(int(expected_exits), num_validators)

        remaining = 1.0 - actual_exits / num_validators if num_validators > 0 else 1.0
        return actual_exits, remaining

    def compute_metrics(self, stale_rate: float, num_validators: int) -> dict:
        """Compute all economics metrics for a given stale rate.

        Args:
            stale_rate: Current stale rate.
            num_validators: Current validator count.

        Returns:
            Dictionary of economics metrics.
        """
        exits, remaining = self.network_shrinkage(stale_rate, num_validators)
        return {
            "break_even_stale_rate": round(self.break_even_stale_rate(), 6),
            "profit_margin": round(self.profit_margin(stale_rate), 6),
            "exit_probability": round(self.exit_probability(stale_rate), 6),
            "estimated_validator_exits": exits,
            "remaining_validators_fraction": round(remaining, 6),
            "cost_per_slot_usd": round(self.config.cost_per_slot_usd, 8),
            "reward_per_slot_usd": self.config.block_reward_per_slot_usd,
        }
