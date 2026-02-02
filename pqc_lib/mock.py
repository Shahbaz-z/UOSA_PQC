"""Deterministic mock implementations for hosting without liboqs.

When liboqs is unavailable or PQC_MOCK=1 is set, the library falls back
to these mocks. All sizes match the real algorithms so the UI and
block-space model remain accurate.
"""

import os
import hashlib
from typing import Tuple

# ---------------------------------------------------------------------------
# Detect mock mode
# ---------------------------------------------------------------------------
_force_mock = os.getenv("PQC_MOCK", "0") == "1"

try:
    if _force_mock:
        raise ImportError("Mock mode forced via PQC_MOCK=1")
    import oqs  # noqa: F401

    MOCK_MODE = False
except ImportError:
    MOCK_MODE = True

# ---------------------------------------------------------------------------
# Algorithm size tables (bytes) – sourced from NIST PQC standards
# ---------------------------------------------------------------------------
KEM_PARAMS = {
    "Kyber512": {
        "public_key": 800,
        "secret_key": 1632,
        "ciphertext": 768,
        "shared_secret": 32,
    },
    "Kyber768": {
        "public_key": 1184,
        "secret_key": 2400,
        "ciphertext": 1088,
        "shared_secret": 32,
    },
    "Kyber1024": {
        "public_key": 1568,
        "secret_key": 3168,
        "ciphertext": 1568,
        "shared_secret": 32,
    },
    # FIPS 203 (ML-KEM) – identical parameters to Kyber, standardized names
    "ML-KEM-512": {
        "public_key": 800,
        "secret_key": 1632,
        "ciphertext": 768,
        "shared_secret": 32,
    },
    "ML-KEM-768": {
        "public_key": 1184,
        "secret_key": 2400,
        "ciphertext": 1088,
        "shared_secret": 32,
    },
    "ML-KEM-1024": {
        "public_key": 1568,
        "secret_key": 3168,
        "ciphertext": 1568,
        "shared_secret": 32,
    },
}

SIG_PARAMS = {
    "Dilithium2": {
        "public_key": 1312,
        "secret_key": 2528,
        "signature": 2420,
    },
    "Dilithium3": {
        "public_key": 1952,
        "secret_key": 4000,
        "signature": 3293,
    },
    "Dilithium5": {
        "public_key": 2592,
        "secret_key": 4864,
        "signature": 4595,
    },
    # FIPS 204 (ML-DSA) – identical parameters to Dilithium, standardized names
    "ML-DSA-44": {
        "public_key": 1312,
        "secret_key": 2528,
        "signature": 2420,
    },
    "ML-DSA-65": {
        "public_key": 1952,
        "secret_key": 4000,
        "signature": 3293,
    },
    "ML-DSA-87": {
        "public_key": 2592,
        "secret_key": 4864,
        "signature": 4595,
    },
    # Falcon (NIST PQC Round 3 alternate, compact signatures)
    "Falcon-512": {
        "public_key": 897,
        "secret_key": 1281,
        "signature": 666,
    },
    "Falcon-1024": {
        "public_key": 1793,
        "secret_key": 2305,
        "signature": 1280,
    },
}

ED25519_PARAMS = {
    "public_key": 32,
    "secret_key": 64,
    "signature": 64,
}

# Algorithms that support hybrid mode (Ed25519 + PQC)
HYBRIDABLE_SIGS = [
    "Dilithium2", "Dilithium3", "Dilithium5",
    "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
    "Falcon-512", "Falcon-1024",
]


def _deterministic_bytes(label: str, length: int) -> bytes:
    """Return repeatable pseudo-random bytes for a given label."""
    out = b""
    i = 0
    while len(out) < length:
        out += hashlib.sha256(f"{label}:{i}".encode()).digest()
        i += 1
    return out[:length]


# ---------------------------------------------------------------------------
# Mock KEM
# ---------------------------------------------------------------------------
def mock_kem_keygen(algorithm: str) -> Tuple[bytes, bytes]:
    p = KEM_PARAMS[algorithm]
    pk = _deterministic_bytes(f"{algorithm}-pk", p["public_key"])
    sk = _deterministic_bytes(f"{algorithm}-sk", p["secret_key"])
    return pk, sk


def mock_kem_encaps(algorithm: str, public_key: bytes) -> Tuple[bytes, bytes]:
    p = KEM_PARAMS[algorithm]
    ct = _deterministic_bytes(f"{algorithm}-ct", p["ciphertext"])
    ss = _deterministic_bytes(f"{algorithm}-ss", p["shared_secret"])
    return ct, ss


def mock_kem_decaps(algorithm: str, secret_key: bytes, ciphertext: bytes) -> bytes:
    p = KEM_PARAMS[algorithm]
    return _deterministic_bytes(f"{algorithm}-ss", p["shared_secret"])


# ---------------------------------------------------------------------------
# Mock Signatures
# ---------------------------------------------------------------------------
def mock_sig_keygen(algorithm: str) -> Tuple[bytes, bytes]:
    p = SIG_PARAMS[algorithm]
    pk = _deterministic_bytes(f"{algorithm}-sig-pk", p["public_key"])
    sk = _deterministic_bytes(f"{algorithm}-sig-sk", p["secret_key"])
    return pk, sk


def mock_sign(algorithm: str, secret_key: bytes, message: bytes) -> bytes:
    p = SIG_PARAMS[algorithm]
    return _deterministic_bytes(f"{algorithm}-sig", p["signature"])


def mock_verify(algorithm: str, public_key: bytes, message: bytes, signature: bytes) -> bool:
    # In mock mode, verification always succeeds for mock-generated signatures
    expected = mock_sign(algorithm, b"", message)
    return signature == expected


# ---------------------------------------------------------------------------
# Mock Ed25519
# ---------------------------------------------------------------------------
def mock_ed25519_keygen() -> Tuple[bytes, bytes]:
    pk = _deterministic_bytes("ed25519-pk", ED25519_PARAMS["public_key"])
    sk = _deterministic_bytes("ed25519-sk", ED25519_PARAMS["secret_key"])
    return pk, sk


def mock_ed25519_sign(secret_key: bytes, message: bytes) -> bytes:
    return _deterministic_bytes("ed25519-sig", ED25519_PARAMS["signature"])


def mock_ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    expected = mock_ed25519_sign(b"", message)
    return signature == expected
