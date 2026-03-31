"""Agent-based model of user fee behaviour under PQC-induced fee pressure.

Real users are not homogeneous. Under PQC, transaction fees rise because:
  1. Blocks hold fewer transactions (larger PQC sigs consume more block space).
  2. Base fees increase to ration the reduced block space.
  3. Priority fees spike as high-value users compete for limited slots.

This module models five archetypes with heterogeneous price elasticity:
  - retail:         High elasticity. Abandons or batches if fee too high.
  - whale:          Low elasticity. Pays large premiums, absorbs fee shock.
  - arb_bot:        Zero delay tolerance. Pays any fee; abandons if too slow.
  - defi_protocol:  Medium elasticity. Migrates to L2 if sustained pressure.
  - exchange:       Low elasticity for priority; batches withdrawals efficiently.

These agents can be combined into an AgentPool that simulates how
collective demand responds to rising fees — creating realistic demand
destruction feedback loops for the DESEngine.

References:
    - EIP-1559 fee market mechanics: https://eips.ethereum.org/EIPS/eip-1559
    - Solana priority fees: https://solana.com/docs/core/fees
    - Bitcoin mempool fee market: https://bitcoinops.org/en/topics/fee-estimation/
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Agent type definitions
# ---------------------------------------------------------------------------

# Default parameters per agent type.
# max_fee_ratio: Maximum fee as a fraction of transaction VALUE (not absolute).
# batch_threshold_ratio: Start batching when fee rate exceeds this × baseline.
# l2_migration_threshold_ratio: Migrate to L2 when fee exceeds this × baseline.
# l2_migration_min_blocks: Blocks at elevated fees before migration triggers.

AGENT_DEFAULTS: Dict[str, Dict] = {
    "retail": {
        "max_fee_ratio":               0.05,   # 5% of tx value
        "batch_threshold_ratio":       2.0,    # batch if fee > 2× baseline
        "l2_migration_threshold_ratio": 5.0,   # migrate if fee > 5× baseline
        "l2_migration_min_blocks":     50,
        "delay_tolerance_slots":       20,     # accepts up to 20 slots of delay
        "wallet_balance_usd_mean":     2_000,
        "tx_value_usd_mean":           150,
    },
    "whale": {
        "max_fee_ratio":               0.01,   # 1% of (large) tx value → big abs fees
        "batch_threshold_ratio":       20.0,   # never batches
        "l2_migration_threshold_ratio": 50.0,  # essentially never migrates
        "l2_migration_min_blocks":     1_000,
        "delay_tolerance_slots":       5,
        "wallet_balance_usd_mean":     500_000,
        "tx_value_usd_mean":           50_000,
    },
    "arb_bot": {
        "max_fee_ratio":               0.50,   # 50% of arb profit margin
        "batch_threshold_ratio":       100.0,  # never batches (time-sensitive)
        "l2_migration_threshold_ratio": 10.0,  # abandons arb if L2 is faster
        "l2_migration_min_blocks":     2,      # very quick L2 pivot
        "delay_tolerance_slots":       2,      # abandon if wait > 2 slots
        "wallet_balance_usd_mean":     20_000,
        "tx_value_usd_mean":           5_000,
    },
    "defi_protocol": {
        "max_fee_ratio":               0.02,   # 2% of position value
        "batch_threshold_ratio":       3.0,
        "l2_migration_threshold_ratio": 5.0,   # moves to L2 if sustained pressure
        "l2_migration_min_blocks":     100,    # needs extended period to trigger
        "delay_tolerance_slots":       10,
        "wallet_balance_usd_mean":     1_000_000,
        "tx_value_usd_mean":           10_000,
    },
    "exchange": {
        "max_fee_ratio":               0.001,  # very low per-withdrawal target
        "batch_threshold_ratio":       1.5,    # starts batching at any pressure
        "l2_migration_threshold_ratio": 10.0,
        "l2_migration_min_blocks":     500,
        "delay_tolerance_slots":       100,    # tolerates delay for batch savings
        "wallet_balance_usd_mean":     10_000_000,
        "tx_value_usd_mean":           1_000,  # per withdrawal
    },
}


# Realistic chain-specific agent population mixes
CHAIN_AGENT_MIX: Dict[str, Dict[str, float]] = {
    "bitcoin": {
        "retail":       0.60,
        "whale":        0.10,
        "arb_bot":      0.05,
        "defi_protocol": 0.00,   # negligible on Bitcoin L1
        "exchange":     0.25,
    },
    "ethereum": {
        "retail":       0.40,
        "whale":        0.10,
        "arb_bot":      0.20,
        "defi_protocol": 0.20,
        "exchange":     0.10,
    },
    "solana": {
        "retail":       0.30,
        "whale":        0.05,
        "arb_bot":      0.40,
        "defi_protocol": 0.20,
        "exchange":     0.05,
    },
}


# ---------------------------------------------------------------------------
# UserAgent dataclass
# ---------------------------------------------------------------------------

@dataclass
class UserAgent:
    """A single user agent with heterogeneous fee sensitivity.

    Attributes:
        agent_type:                  One of the defined archetypes.
        wallet_balance_usd:          Wallet balance (USD).
        tx_value_usd:                Value of the transaction being submitted (USD).
        max_fee_ratio:               Max acceptable fee as a fraction of tx_value_usd.
        batch_threshold_ratio:       Batch if fee_rate > batch_threshold_ratio × baseline.
        l2_migration_threshold_ratio: Migrate to L2 if fee_rate exceeds this × baseline.
        l2_migration_min_blocks:     Blocks at elevated fees before L2 migration triggers.
        delay_tolerance_slots:       Maximum mempool wait (slots) before abandoning.
    """

    agent_type: str
    wallet_balance_usd: float
    tx_value_usd: float
    max_fee_ratio: float
    batch_threshold_ratio: float
    l2_migration_threshold_ratio: float
    l2_migration_min_blocks: int
    delay_tolerance_slots: int = 20
    random_seed: Optional[int] = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.random_seed)

    @property
    def max_absolute_fee_usd(self) -> float:
        """Maximum fee in USD this agent is willing to pay."""
        return self.max_fee_ratio * self.tx_value_usd

    def will_submit(
        self,
        current_fee_rate: float,
        baseline_fee_rate: float,
    ) -> bool:
        """Whether the agent will submit the transaction at the current fee.

        Args:
            current_fee_rate:  Current mempool fee rate (e.g. sat/vbyte, gwei, lamports).
            baseline_fee_rate: Classical baseline fee rate (before PQC inflation).

        Returns:
            True if the agent submits; False if it abandons.
        """
        if baseline_fee_rate <= 0:
            return True
        ratio = current_fee_rate / baseline_fee_rate

        # Agent abandons if fee exceeds its threshold
        # Add a small random perturbation to model individual variation
        noise = 1.0 + self._rng.gauss(0, 0.1)
        adjusted_threshold = self.batch_threshold_ratio * noise

        return ratio <= adjusted_threshold

    def will_batch(
        self,
        current_fee_rate: float,
        baseline_fee_rate: float,
    ) -> bool:
        """Whether the agent will batch transactions at the current fee.

        Args:
            current_fee_rate:  Current fee rate.
            baseline_fee_rate: Baseline fee rate.

        Returns:
            True if agent switches to batching mode.
        """
        if baseline_fee_rate <= 0:
            return False
        ratio = current_fee_rate / baseline_fee_rate
        return ratio >= self.batch_threshold_ratio

    def will_migrate_l2(
        self,
        current_fee_rate: float,
        baseline_fee_rate: float,
        blocks_elevated: int,
    ) -> bool:
        """Whether the agent migrates to an L2/sidechain.

        Migration requires BOTH the fee threshold AND a minimum sustained
        elevated period (agents don't react instantly to temporary spikes).

        Args:
            current_fee_rate:  Current fee rate.
            baseline_fee_rate: Baseline fee rate.
            blocks_elevated:   Consecutive blocks with elevated fees.

        Returns:
            True if the agent migrates to L2.
        """
        if baseline_fee_rate <= 0:
            return False
        ratio = current_fee_rate / baseline_fee_rate
        return (
            ratio >= self.l2_migration_threshold_ratio
            and blocks_elevated >= self.l2_migration_min_blocks
        )

    def batch_size(
        self,
        current_fee_rate: float,
        baseline_fee_rate: float,
    ) -> int:
        """Optimal batch size given current fee pressure.

        Exchanges batch withdrawals; batch size scales with fee pressure
        so that total fee cost stays roughly constant.

        Args:
            current_fee_rate:  Current fee rate.
            baseline_fee_rate: Baseline fee rate.

        Returns:
            Batch size (1 = no batching, N = N txs bundled into one).
        """
        if not self.will_batch(current_fee_rate, baseline_fee_rate):
            return 1
        if baseline_fee_rate <= 0:
            return 1
        ratio = current_fee_rate / baseline_fee_rate
        # Batch size proportional to fee pressure; floor at 1, cap at 100
        return max(1, min(100, int(ratio)))

    def effective_tx_size_bytes(
        self,
        sig_algorithm: str,
        batch_size: int = 1,
        chain: str = "ethereum",
    ) -> int:
        """Effective byte contribution per logical transaction after batching.

        Args:
            sig_algorithm: Signature algorithm.
            batch_size:    Number of logical txs in one on-chain tx.
            chain:         Chain name (affects per-tx overhead).

        Returns:
            Effective bytes per logical transaction (wire bytes / batch_size).
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        sig_size = SIGNATURE_SIZES.get(sig_algorithm, 64)
        pk_size  = PUBLIC_KEY_SIZES.get(sig_algorithm, 32)

        # Rough chain-specific overhead per batch tx
        overhead = {
            "bitcoin":  180,  # base UTXO overhead per input/output
            "ethereum": 120,  # base ETH tx overhead
            "solana":   250,  # Solana tx header + accounts
        }.get(chain, 180)

        # Sig/pk amortised across batch; overhead per output is marginal
        # (30 bytes / extra output for simple sends)
        per_batch_sig = sig_size + pk_size
        extra_output_cost = 30 * max(0, batch_size - 1)
        total_wire = overhead + per_batch_sig + extra_output_cost
        return max(1, total_wire // batch_size)


# ---------------------------------------------------------------------------
# AgentPool
# ---------------------------------------------------------------------------

@dataclass
class AgentPool:
    """A population of heterogeneous user agents for a given chain.

    Attributes:
        chain:      Target chain ("bitcoin", "ethereum", "solana").
        pool_size:  Total number of agents.
        seed:       Random seed for reproducibility.
        mix_override: Optional override for agent type fractions.
    """

    chain: str       = "ethereum"
    pool_size: int   = 1_000
    seed: int        = 42
    mix_override: Optional[Dict[str, float]] = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._agents: List[UserAgent] = self._generate_agents()

    def _agent_mix(self) -> Dict[str, float]:
        """Return the agent type fractions for this pool."""
        if self.mix_override:
            return self.mix_override
        return CHAIN_AGENT_MIX.get(self.chain, CHAIN_AGENT_MIX["ethereum"])

    def _generate_agents(self) -> List[UserAgent]:
        """Generate the agent population."""
        agents: List[UserAgent] = []
        mix = self._agent_mix()

        for agent_type, fraction in mix.items():
            n = max(1, int(fraction * self.pool_size))
            defaults = AGENT_DEFAULTS.get(agent_type, AGENT_DEFAULTS["retail"])

            for _ in range(n):
                # Sample wallet balance and tx value with log-normal variation
                balance = max(1.0, self._rng.lognormvariate(
                    math.log(defaults["wallet_balance_usd_mean"]), 1.0
                ))
                tx_val = max(1.0, self._rng.lognormvariate(
                    math.log(defaults["tx_value_usd_mean"]), 0.8
                ))

                agents.append(UserAgent(
                    agent_type=agent_type,
                    wallet_balance_usd=balance,
                    tx_value_usd=tx_val,
                    max_fee_ratio=defaults["max_fee_ratio"],
                    batch_threshold_ratio=defaults["batch_threshold_ratio"],
                    l2_migration_threshold_ratio=defaults["l2_migration_threshold_ratio"],
                    l2_migration_min_blocks=defaults["l2_migration_min_blocks"],
                    delay_tolerance_slots=defaults["delay_tolerance_slots"],
                    random_seed=self._rng.randint(0, 2**31),
                ))

        return agents

    @property
    def agents(self) -> List[UserAgent]:
        """List of all agents in the pool."""
        return self._agents

    def agents_by_type(self, agent_type: str) -> List[UserAgent]:
        """Return all agents of a given type."""
        return [a for a in self._agents if a.agent_type == agent_type]

    def simulate_block_demand(
        self,
        current_fee_rate: float,
        baseline_fee_rate: float,
        sig_algorithm: str,
        blocks_elevated: int = 0,
    ) -> Dict:
        """Simulate block-level transaction demand given current fee conditions.

        For each agent, determines whether they submit, batch, abandon, or
        migrate to L2. Returns aggregate counts for use in the DESEngine.

        Args:
            current_fee_rate:  Current mempool fee rate.
            baseline_fee_rate: Classical baseline fee rate.
            sig_algorithm:     Signature algorithm in use.
            blocks_elevated:   Consecutive blocks at elevated fees (for L2 trigger).

        Returns:
            Dict with txs_submitted, txs_abandoned, txs_batched,
            l2_migrations, effective_demand_bytes, demand_reduction_pct.
        """
        txs_submitted  = 0
        txs_abandoned  = 0
        txs_batched    = 0
        l2_migrations  = 0
        demand_bytes   = 0

        for agent in self._agents:
            if agent.will_migrate_l2(current_fee_rate, baseline_fee_rate, blocks_elevated):
                l2_migrations += 1
                continue

            if not agent.will_submit(current_fee_rate, baseline_fee_rate):
                txs_abandoned += 1
                continue

            bs = agent.batch_size(current_fee_rate, baseline_fee_rate)
            if bs > 1:
                txs_batched += 1
            txs_submitted += 1

            eff_bytes = agent.effective_tx_size_bytes(
                sig_algorithm, batch_size=bs, chain=self.chain
            )
            demand_bytes += eff_bytes

        total = len(self._agents)
        baseline_demand = sum(
            a.effective_tx_size_bytes(sig_algorithm, batch_size=1, chain=self.chain)
            for a in self._agents
        )

        return {
            "txs_submitted":         txs_submitted,
            "txs_abandoned":         txs_abandoned,
            "txs_batched":           txs_batched,
            "l2_migrations":         l2_migrations,
            "total_agents":          total,
            "effective_demand_bytes": demand_bytes,
            "baseline_demand_bytes": baseline_demand,
            "demand_reduction_pct":  (
                100.0 * (1 - demand_bytes / baseline_demand)
                if baseline_demand > 0 else 0.0
            ),
            "submission_rate":       txs_submitted / total if total > 0 else 0.0,
        }

    def fee_elasticity_curve(
        self,
        baseline_fee_rate: float,
        max_multiplier: float = 20.0,
        steps: int = 40,
        sig_algorithm: str = "ECDSA",
    ) -> List[Dict]:
        """Compute demand curve: txs submitted as a function of fee multiplier.

        Args:
            baseline_fee_rate: Classical baseline fee rate.
            max_multiplier:    Maximum fee multiplier to test.
            steps:             Number of multiplier steps.
            sig_algorithm:     Signature algorithm.

        Returns:
            List of dicts, one per fee level.
        """
        results = []
        for i in range(steps + 1):
            multiplier   = 1.0 + (max_multiplier - 1.0) * i / steps
            current_rate = baseline_fee_rate * multiplier
            demand       = self.simulate_block_demand(
                current_fee_rate  = current_rate,
                baseline_fee_rate = baseline_fee_rate,
                sig_algorithm     = sig_algorithm,
                blocks_elevated   = 0,
            )
            demand["fee_multiplier"] = multiplier
            demand["fee_rate"]       = current_rate
            results.append(demand)
        return results


# Avoid circular import issue with math
import math
