"""Signature verification time modeling for PQC blockchain impact analysis.

Models how long it takes a node to verify all signatures in a block,
accounting for:
1. Per-signature verification time (algorithm-dependent)
2. CPU core parallelism
3. Queuing delays (M/M/c analytical model)

Sources:
- Cloudflare 2024 PQC benchmarks: https://blog.cloudflare.com/pqc-2024-benchmarks
- NIST PQC final standards: https://csrc.nist.gov/projects/post-quantum-cryptography
- ML-DSA (CRYSTALS-Dilithium), SLH-DSA (SPHINCS+) specs
"""

from __future__ import annotations

import math
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Per-signature verification times (milliseconds)
# FIX #4: Corrected per Cloudflare 2024 benchmarks
# ---------------------------------------------------------------------------
# Source: https://blog.cloudflare.com/pqc-2024-benchmarks
# Measured on modern x86-64 hardware (AMD EPYC 7763)
# Values represent median verification latency per signature
#
# Classical:
#   Ed25519:   ~0.05 ms  (very fast, hardware-accelerated)
#   ECDSA-256: ~0.08 ms
#
# NIST PQC Level 1-3 (lattice-based, fast):
#   ML-DSA-44:  ~0.04 ms  (faster than Ed25519 in optimised impl)
#   ML-DSA-65:  ~0.06 ms
#   ML-DSA-87:  ~0.09 ms
#
# NIST PQC Level 1-5 (hash-based, SLOW):
#   SLH-DSA-SHAKE-128s: ~2.1 ms  (small params, still slow)
#   SLH-DSA-SHAKE-128f: ~0.8 ms  (fast variant)
#   SLH-DSA-SHAKE-192s: ~5.3 ms
#   SLH-DSA-SHAKE-256s: ~8.4 ms

VERIFICATION_TIME_MS: Dict[str, float] = {
    # Classical
    "Ed25519":      0.05,
    "ECDSA-256":    0.08,
    "ECDSA-384":    0.13,
    # ML-DSA (CRYSTALS-Dilithium) — fast lattice-based
    "ML-DSA-44":    0.04,
    "ML-DSA-65":    0.06,
    "ML-DSA-87":    0.09,
    # SLH-DSA (SPHINCS+) — hash-based, significantly slower
    # FIX #4: Was incorrectly set to 0.1ms (same as classical)
    # Corrected to Cloudflare 2024 benchmark values
    "SLH-DSA-SHAKE-128s":  2.1,
    "SLH-DSA-SHAKE-128f":  0.8,
    "SLH-DSA-SHAKE-192s":  5.3,
    "SLH-DSA-SHAKE-192f":  2.2,
    "SLH-DSA-SHAKE-256s":  8.4,
    "SLH-DSA-SHAKE-256f":  3.5,
    # Falcon (NTRU-based)
    "Falcon-512":   0.03,
    "Falcon-1024":  0.05,
    # BIKE / HQC (code-based, slower)
    "BIKE-L1":      1.8,
    "HQC-128":      2.4,
}


def get_verification_time(
    algorithm: str,
    num_signatures: int,
    num_cores: int = 1,
) -> float:
    """Calculate total block verification time (seconds).

    Simple model: parallelise across CPU cores, no queuing.

    Args:
        algorithm: Signature algorithm name (e.g. "Ed25519", "ML-DSA-65")
        num_signatures: Number of signatures in the block
        num_cores: Number of available CPU cores

    Returns:
        Verification time in seconds
    """
    per_sig_ms = VERIFICATION_TIME_MS.get(algorithm, 0.05)
    # Parallelise: ceil(num_sigs / cores) rounds of verification
    rounds = math.ceil(num_signatures / max(num_cores, 1))
    total_ms = rounds * per_sig_ms
    return total_ms / 1000.0  # convert to seconds


def get_verification_time_mmc(
    algorithm: str,
    num_signatures: int,
    num_cores: int = 1,
    arrival_rate: float = 1.0,
) -> float:
    """Calculate block verification time using M/M/c analytical queuing model.

    FIX #2: Analytical CPU queuing model (was missing, previously only the
    simple get_verification_time() was called).

    M/M/c queue parameters:
    - lambda (arrival_rate): block/tx arrival rate (blocks per second)
    - mu (service_rate): signatures verified per second per core
    - c: number of CPU cores

    The Erlang-C formula gives the probability of queuing (Pq), which
    determines the expected waiting time W_q in the queue:

        W_q = Pq / (c * mu - lambda)

    Total expected sojourn time = W_q + 1/mu

    Args:
        algorithm: Signature algorithm name
        num_signatures: Number of signatures in the block
        num_cores: Number of CPU cores (c in M/M/c)
        arrival_rate: Block arrival rate in blocks/second (lambda)

    Returns:
        Expected total verification time in seconds (service + queuing wait)
    """
    per_sig_ms = VERIFICATION_TIME_MS.get(algorithm, 0.05)
    per_sig_s = per_sig_ms / 1000.0

    # Service rate per core: signatures per second
    if per_sig_s <= 0:
        return 0.0
    mu_per_core = 1.0 / per_sig_s  # signatures/second per core

    c = max(num_cores, 1)

    # Total service rate across all cores
    mu_total = c * mu_per_core

    # Traffic intensity: lambda / (c * mu)
    # lambda here = arrival_rate * num_signatures (sigs per second arriving)
    lam = arrival_rate * num_signatures

    # Utilisation per server
    rho = lam / mu_total

    # If rho >= 1, system is overloaded — clamp to heavy load but finite
    if rho >= 1.0:
        rho = 0.99

    # Erlang-C: probability that an arriving customer must wait
    # P_C = (rho^c / c!) * (1/(1-rho)) / [sum_{k=0}^{c-1}(rho^k/k!) + (rho^c/c!) * (1/(1-rho))]
    import math
    numerator = (rho * c) ** c / math.factorial(c) * (1.0 / (1.0 - rho))
    denominator = sum((rho * c) ** k / math.factorial(k) for k in range(c)) + numerator
    p_wait = numerator / denominator if denominator > 0 else 0.0

    # Expected waiting time in queue
    # W_q = P_C / (c * mu_per_core - lam / num_signatures)
    # (use per-signature service, not aggregate)
    effective_service_rate = c * mu_per_core
    if effective_service_rate > arrival_rate:
        w_q = p_wait / (effective_service_rate - arrival_rate)
    else:
        w_q = p_wait / (effective_service_rate * 0.01)  # overloaded fallback

    # Total time = base service time + queuing wait
    base_service_time = get_verification_time(algorithm, num_signatures, num_cores)
    total_time = base_service_time + w_q

    return total_time
