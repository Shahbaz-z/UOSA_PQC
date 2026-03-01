"""Phase 2: Stochastic transaction arrival model.

Implements a Poisson process for transaction arrivals with configurable
rate parameter (λ). Inter-arrival times follow an exponential distribution.

Physics motivation:
  - Blockchain transaction submissions are approximately Poisson-distributed
    (independent arrivals from many users → Poisson limit theorem).
  - Exponential inter-arrival times capture the memoryless property.
  - The rate λ can be varied to simulate calm vs. congested conditions.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class PoissonArrivalModel:
    """Poisson process transaction generator.

    Generates exponentially-distributed inter-arrival times.
    λ (lambda_tps) is the average arrival rate in transactions per second.

    Attributes:
        lambda_tps: Average transactions per second.
        rng: Seeded random generator for reproducibility.
    """

    lambda_tps: float
    rng: random.Random

    def __post_init__(self) -> None:
        if self.lambda_tps <= 0:
            raise ValueError(
                f"lambda_tps must be positive, got {self.lambda_tps}"
            )

    def next_inter_arrival_ms(self) -> float:
        """Sample the next inter-arrival time in milliseconds.

        Returns:
            Time until next transaction, in ms.
            Drawn from Exponential(1/λ), converted to ms.
        """
        # expovariate(lambd) returns sample from Exp(lambd)
        # We want mean = 1/λ seconds = 1000/λ ms
        inter_arrival_s = self.rng.expovariate(self.lambda_tps)
        return inter_arrival_s * 1000.0

    def expected_count_in_interval(self, interval_ms: float) -> float:
        """Expected number of arrivals in a given interval.

        Args:
            interval_ms: Time interval in milliseconds.

        Returns:
            Expected count (λ × interval_seconds).
        """
        return self.lambda_tps * (interval_ms / 1000.0)
