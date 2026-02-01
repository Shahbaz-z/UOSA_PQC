"""Kyber KEM wrapper with automatic mock fallback.

Supports Kyber512, Kyber768, and Kyber1024 via liboqs-python.
If liboqs is unavailable, transparently uses mock implementations
with correct artifact sizes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from pqc_lib.mock import MOCK_MODE, KEM_PARAMS
from pqc_lib.utils import timed_call

if not MOCK_MODE:
    import oqs

KEM_ALGORITHMS = list(KEM_PARAMS.keys())


@dataclass
class KEMKeypair:
    algorithm: str
    public_key: bytes
    secret_key: bytes
    keygen_time_ms: float
    peak_memory_kb: float


@dataclass
class EncapsResult:
    algorithm: str
    ciphertext: bytes
    shared_secret: bytes
    time_ms: float
    peak_memory_kb: float


@dataclass
class DecapsResult:
    algorithm: str
    shared_secret: bytes
    time_ms: float
    peak_memory_kb: float


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def keygen(algorithm: str) -> KEMKeypair:
    """Generate a KEM keypair for *algorithm*."""
    if algorithm not in KEM_ALGORITHMS:
        raise ValueError(f"Unknown KEM algorithm: {algorithm}. Choose from {KEM_ALGORITHMS}")

    if MOCK_MODE:
        from pqc_lib.mock import mock_kem_keygen

        tr = timed_call(mock_kem_keygen, algorithm)
        pk, sk = tr.result
    else:
        kem = oqs.KeyEncapsulation(algorithm)
        tr = timed_call(kem.generate_keypair)
        pk = tr.result
        sk = kem.export_secret_key()

    return KEMKeypair(
        algorithm=algorithm,
        public_key=pk,
        secret_key=sk,
        keygen_time_ms=tr.elapsed_ms,
        peak_memory_kb=tr.peak_memory_kb,
    )


def encaps(algorithm: str, public_key: bytes) -> EncapsResult:
    """Encapsulate a shared secret using *public_key*."""
    if MOCK_MODE:
        from pqc_lib.mock import mock_kem_encaps

        tr = timed_call(mock_kem_encaps, algorithm, public_key)
        ct, ss = tr.result
    else:
        kem = oqs.KeyEncapsulation(algorithm)
        tr = timed_call(kem.encap_secret, public_key)
        ct, ss = tr.result

    return EncapsResult(
        algorithm=algorithm,
        ciphertext=ct,
        shared_secret=ss,
        time_ms=tr.elapsed_ms,
        peak_memory_kb=tr.peak_memory_kb,
    )


def decaps(algorithm: str, secret_key: bytes, ciphertext: bytes) -> DecapsResult:
    """Decapsulate *ciphertext* using *secret_key*."""
    if MOCK_MODE:
        from pqc_lib.mock import mock_kem_decaps

        tr = timed_call(mock_kem_decaps, algorithm, secret_key, ciphertext)
        ss = tr.result
    else:
        kem = oqs.KeyEncapsulation(algorithm, secret_key)
        tr = timed_call(kem.decap_secret, ciphertext)
        ss = tr.result

    return DecapsResult(
        algorithm=algorithm,
        shared_secret=ss,
        time_ms=tr.elapsed_ms,
        peak_memory_kb=tr.peak_memory_kb,
    )
