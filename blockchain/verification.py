"""Signature verification time modeling for PQC blockchain impact analysis.

Models how long it takes to verify all signatures in a block, identifying
whether verification time (not just block space) becomes the throughput
bottleneck with PQC schemes.

Verification times are calibrated from:
- liboqs benchmark data (ML-DSA, SLH-DSA, Falcon)
- libsodium / dalek benchmarks (Ed25519)
- OpenSSL benchmarks (ECDSA secp256k1, Schnorr)
- Published academic benchmarks for cross-validation

All times assume a single-core baseline. Parallel verification is modeled
by dividing across available cores where the algorithm supports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class VerificationProfile:
    """Verification characteristics for a signature algorithm."""
    algorithm: str
    verify_time_us: float       # Microseconds per single verification
    batch_speedup: float        # Multiplier when batch-verifying (1.0 = no speedup, 0.5 = 2x faster)
    parallelizable: bool        # Can verifications be parallelized across cores


@dataclass
class VerificationResult:
    """Result of block verification time analysis."""
    algorithm: str
    txs_in_block: int
    serial_time_ms: float           # Total time if verifying sequentially (single core)
    parallel_time_ms: float         # Time with parallel verification across cores
    num_cores: int
    block_time_ms: float            # Chain's block time for comparison
    exceeds_block_time: bool        # True if verification takes longer than block production
    verification_bottleneck_ratio: float  # parallel_time / block_time (>1.0 = bottleneck)
    effective_tps: float            # TPS limited by verification capacity


# ---------------------------------------------------------------------------
# Verification time catalog
# ---------------------------------------------------------------------------
# Sources:
# - Ed25519: ~60μs (libsodium, dalek-cryptography benchmarks)
# - ECDSA secp256k1: ~80μs (OpenSSL, libsecp256k1)
# - Schnorr BIP340: ~60μs (libsecp256k1, batch-friendly)
# - ML-DSA: liboqs benchmarks on x86-64 (AVX2)
#   ML-DSA-44: ~180μs verify, ML-DSA-65: ~300μs, ML-DSA-87: ~500μs
# - SLH-DSA: liboqs benchmarks (hash-heavy, slower)
#   128s: ~3000μs, 128f: ~500μs, 192s: ~5500μs, 192f: ~1000μs, 256s: ~8000μs, 256f: ~2000μs
# - Falcon: liboqs benchmarks
#   Falcon-512: ~100μs, Falcon-1024: ~200μs (fast verify is a key advantage)
#
# Batch speedup:
# - Ed25519: 0.5 (batch verification via Bos-Coster / Pippenger)
# - Schnorr: 0.4 (MuSig-style batch, most efficient)
# - Others: 1.0 (no standardized batch verify for lattice/hash-based)
# ---------------------------------------------------------------------------

VERIFICATION_PROFILES: Dict[str, VerificationProfile] = {
    # Classical baselines
    "Ed25519": VerificationProfile("Ed25519", 60.0, 0.5, True),
    "ECDSA": VerificationProfile("ECDSA", 80.0, 1.0, True),
    "Schnorr": VerificationProfile("Schnorr", 60.0, 0.4, True),
    "BLS12-381": VerificationProfile("BLS12-381", 1500.0, 1.0, True),  # pairing-based

    # ML-DSA (FIPS 204) -- lattice-based
    "ML-DSA-44": VerificationProfile("ML-DSA-44", 180.0, 1.0, True),
    "ML-DSA-65": VerificationProfile("ML-DSA-65", 300.0, 1.0, True),
    "ML-DSA-87": VerificationProfile("ML-DSA-87", 500.0, 1.0, True),

    # SLH-DSA (FIPS 205) -- hash-based (slow verification, especially "s" variants)
    "SLH-DSA-128s": VerificationProfile("SLH-DSA-128s", 3000.0, 1.0, True),
    "SLH-DSA-128f": VerificationProfile("SLH-DSA-128f", 500.0, 1.0, True),
    "SLH-DSA-192s": VerificationProfile("SLH-DSA-192s", 5500.0, 1.0, True),
    "SLH-DSA-192f": VerificationProfile("SLH-DSA-192f", 1000.0, 1.0, True),
    "SLH-DSA-256s": VerificationProfile("SLH-DSA-256s", 8000.0, 1.0, True),
    "SLH-DSA-256f": VerificationProfile("SLH-DSA-256f", 2000.0, 1.0, True),

    # Falcon (pending FN-DSA) -- fast verification is a key advantage
    "Falcon-512": VerificationProfile("Falcon-512", 100.0, 1.0, True),
    "Falcon-1024": VerificationProfile("Falcon-1024", 200.0, 1.0, True),

    # Hybrids: sum of both verification times
    "Hybrid-Ed25519+ML-DSA-44": VerificationProfile("Hybrid-Ed25519+ML-DSA-44", 60.0 + 180.0, 1.0, True),
    "Hybrid-Ed25519+ML-DSA-65": VerificationProfile("Hybrid-Ed25519+ML-DSA-65", 60.0 + 300.0, 1.0, True),
    "Hybrid-Ed25519+ML-DSA-87": VerificationProfile("Hybrid-Ed25519+ML-DSA-87", 60.0 + 500.0, 1.0, True),
    "Hybrid-Ed25519+Falcon-512": VerificationProfile("Hybrid-Ed25519+Falcon-512", 60.0 + 100.0, 1.0, True),
    "Hybrid-Ed25519+Falcon-1024": VerificationProfile("Hybrid-Ed25519+Falcon-1024", 60.0 + 200.0, 1.0, True),
}


def get_verification_profile(algorithm: str) -> VerificationProfile:
    """Get the verification profile for an algorithm.

    Raises ValueError if the algorithm is not known.
    """
    if algorithm not in VERIFICATION_PROFILES:
        raise ValueError(
            f"Unknown algorithm: {algorithm}. "
            f"Valid: {list(VERIFICATION_PROFILES.keys())}"
        )
    return VERIFICATION_PROFILES[algorithm]


def compute_block_verification_time(
    algorithm: str,
    txs_per_block: int,
    block_time_ms: float,
    num_cores: int = 4,
    use_batch: bool = True,
) -> VerificationResult:
    """Compute how long it takes to verify all signatures in a block.

    Args:
        algorithm: Signature algorithm name.
        txs_per_block: Number of transactions (each with one signature) in the block.
        block_time_ms: Chain's block time in milliseconds.
        num_cores: Number of CPU cores available for parallel verification.
        use_batch: If True, apply batch verification speedup where available.

    Returns:
        VerificationResult with timing analysis and bottleneck detection.
    """
    if txs_per_block < 0:
        raise ValueError(f"txs_per_block must be non-negative, got {txs_per_block}")
    if block_time_ms <= 0:
        raise ValueError(f"block_time_ms must be positive, got {block_time_ms}")
    if num_cores < 1:
        raise ValueError(f"num_cores must be >= 1, got {num_cores}")

    profile = get_verification_profile(algorithm)

    # Serial verification time
    verify_us = profile.verify_time_us
    if use_batch and profile.batch_speedup < 1.0:
        verify_us = verify_us * profile.batch_speedup

    serial_time_us = verify_us * txs_per_block
    serial_time_ms = serial_time_us / 1000.0

    # Parallel verification time
    if profile.parallelizable and num_cores > 1:
        parallel_time_ms = serial_time_ms / num_cores
    else:
        parallel_time_ms = serial_time_ms

    # Bottleneck analysis
    exceeds = parallel_time_ms > block_time_ms
    ratio = parallel_time_ms / block_time_ms if block_time_ms > 0 else float("inf")

    # Effective TPS: how many txs can be verified per second
    if parallel_time_ms > 0:
        verify_capacity_tps = txs_per_block / (parallel_time_ms / 1000.0)
    else:
        verify_capacity_tps = float("inf")

    # Effective TPS is the minimum of block-space TPS and verification TPS
    block_space_tps = txs_per_block / (block_time_ms / 1000.0) if block_time_ms > 0 else 0
    effective_tps = min(block_space_tps, verify_capacity_tps)

    return VerificationResult(
        algorithm=algorithm,
        txs_in_block=txs_per_block,
        serial_time_ms=round(serial_time_ms, 2),
        parallel_time_ms=round(parallel_time_ms, 2),
        num_cores=num_cores,
        block_time_ms=block_time_ms,
        exceeds_block_time=exceeds,
        verification_bottleneck_ratio=round(ratio, 4),
        effective_tps=round(effective_tps, 2),
    )


def compute_verification_limited_tps(
    algorithm: str,
    block_time_ms: float,
    num_cores: int = 4,
    use_batch: bool = True,
) -> float:
    """Compute the maximum TPS a chain can sustain based on verification alone.

    This ignores block space limits and returns the ceiling imposed by
    signature verification speed. The actual TPS is the minimum of this
    value and the block-space-limited TPS.

    Returns:
        Maximum TPS that verification can sustain.
    """
    if block_time_ms <= 0:
        raise ValueError(f"block_time_ms must be positive, got {block_time_ms}")
    if num_cores < 1:
        raise ValueError(f"num_cores must be >= 1, got {num_cores}")

    profile = get_verification_profile(algorithm)

    verify_us = profile.verify_time_us
    if use_batch and profile.batch_speedup < 1.0:
        verify_us = verify_us * profile.batch_speedup

    # How many verifications can we do in one block time?
    block_time_us = block_time_ms * 1000.0
    verifications_per_block = block_time_us / verify_us
    if profile.parallelizable and num_cores > 1:
        verifications_per_block *= num_cores

    tps = verifications_per_block / (block_time_ms / 1000.0)
    return round(tps, 2)
