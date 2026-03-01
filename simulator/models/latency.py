"""Stochastic latency model with physics-motivated distributions.

Network latency follows a log-normal distribution because:
1. Latency is always positive (log-normal has positive support)
2. Network delays are multiplicative products of:
   - Queuing delays at each hop
   - Propagation delays (speed of light in fiber)
   - Processing delays at routers
   - Transmission delays based on link capacity
3. By the Central Limit Theorem, the product of many independent
   positive random variables converges to log-normal
4. Empirical measurements confirm heavy right tails

Alternative: Weibull distribution
- Shape parameter k controls tail behavior
- k > 1: light tail (packet loss truncates high delays)
- k < 1: heavy tail (congestion causes occasional spikes)
- Useful for modeling specific network conditions
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class LatencyModel:
    """Stochastic latency model with configurable distribution.

    Default uses log-normal distribution with specified coefficient
    of variation (CV = std/mean).

    Attributes:
        base_latency_ms: Median latency (geometric mean for log-normal).
        cv: Coefficient of variation (typically 0.10-0.30 for networks).
        distribution: "lognormal" or "weibull".
        weibull_k: Shape parameter for Weibull (only used if distribution="weibull").
    """

    base_latency_ms: float
    cv: float = 0.15  # 15% coefficient of variation
    distribution: str = "lognormal"
    weibull_k: float = 2.5  # Shape parameter for Weibull

    def sample(self, rng: random.Random) -> float:
        """Sample a latency value from the distribution.

        Args:
            rng: Random number generator for reproducibility.

        Returns:
            Sampled latency in milliseconds (always positive).
        """
        if self.distribution == "lognormal":
            return self._sample_lognormal(rng)
        elif self.distribution == "weibull":
            return self._sample_weibull(rng)
        else:
            return self.base_latency_ms

    def _sample_lognormal(self, rng: random.Random) -> float:
        """Sample from log-normal distribution.

        If X ~ LogNormal(mu, sigma), then:
        - median(X) = exp(mu)
        - CV(X) = sqrt(exp(sigma^2) - 1)

        We want median = base_latency_ms and CV = cv.
        Solving:
            sigma = sqrt(log(cv^2 + 1))
            mu = log(base_latency) - sigma^2/2 (to center at base)
        """
        if self.cv <= 0:
            return self.base_latency_ms

        sigma_sq = math.log(self.cv ** 2 + 1)
        sigma = math.sqrt(sigma_sq)
        mu = math.log(self.base_latency_ms) - sigma_sq / 2

        return rng.lognormvariate(mu, sigma)

    def _sample_weibull(self, rng: random.Random) -> float:
        """Sample from Weibull distribution.

        Weibull(k, lambda) where:
        - k is shape (controls tail behavior)
        - lambda is scale (controls location)

        For median = base_latency:
            lambda = base / (ln(2))^(1/k)
        """
        k = self.weibull_k
        scale = self.base_latency_ms / (math.log(2) ** (1 / k))

        return rng.weibullvariate(scale, k)

    def percentile(self, p: float) -> float:
        """Compute the p-th percentile of the distribution.

        Useful for understanding the tail behavior.

        Args:
            p: Percentile (0-100).

        Returns:
            Latency value at the given percentile.
        """
        if self.distribution == "lognormal":
            import statistics

            # For log-normal, percentile is exp(mu + sigma * z_p)
            # where z_p is the standard normal percentile
            sigma_sq = math.log(self.cv ** 2 + 1)
            sigma = math.sqrt(sigma_sq)
            mu = math.log(self.base_latency_ms) - sigma_sq / 2

            # Approximate z_p using inverse error function
            # For common percentiles:
            z_values = {
                50: 0.0,
                75: 0.674,
                90: 1.282,
                95: 1.645,
                99: 2.326,
            }
            z_p = z_values.get(int(p), 0.0)
            return math.exp(mu + sigma * z_p)
        else:
            return self.base_latency_ms


def get_latency_model(region_a: str, region_b: str) -> LatencyModel:
    """Get a latency model for a region pair.

    CV increases slightly for longer distances (more routing hops = more variance).
    """
    from simulator.network.topology import BASE_LATENCY_MATRIX

    if region_a == region_b:
        return LatencyModel(base_latency_ms=1.0, cv=0.10)

    key = tuple(sorted([region_a, region_b]))
    base = BASE_LATENCY_MATRIX.get(key, 150.0)

    # Higher CV for longer distances (more routing hops = more variance)
    # CV ranges from 0.10 (short) to 0.25 (intercontinental)
    cv = 0.10 + (base / 1000) * 0.15
    cv = min(cv, 0.25)

    return LatencyModel(base_latency_ms=base, cv=cv)
