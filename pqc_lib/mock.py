"""Deterministic mock implementations for hosting without liboqs.

When liboqs is unavailable or PQC_MOCK=1 is set, the library falls back
to these mocks.  All artifact sizes match the real NIST-standardized
algorithms so the UI and block-space model remain accurate.

IMPORTANT -- Mock mode limitations:
  - Artifact sizes are NIST-accurate (FIPS 203/204/205).
  - Timing is synthetic (not representative of real hardware performance).
  - Cryptographic security properties are NOT provided: mock verification
    ignores key material and returns True for any mock-generated signature.
    Use real liboqs for security-relevant testing.
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
# Algorithm size tables (bytes) -- sourced from NIST PQC standards
# ---------------------------------------------------------------------------

# FIPS 203 -- ML-KEM (Module-Lattice Key Encapsulation Mechanism)
# Standardized August 2024.  Formerly known as "Kyber" during the NIST
# PQC competition; ML-KEM is the official FIPS standard name.
KEM_PARAMS = {
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

# FIPS 204 -- ML-DSA (Module-Lattice Digital Signature Algorithm)
# Standardized August 2024.  Formerly known as "Dilithium".
#
# FIPS 205 -- SLH-DSA (Stateless Hash-Based Digital Signature Algorithm)
# Standardized August 2024.  Formerly known as "SPHINCS+".
# Hash-based (not lattice) -- different security assumption family.
# "-s" variants are slow/small-sig, "-f" variants are fast/large-sig.
#
# Falcon -- Selected by NIST but NOT YET standardized as a FIPS.
# Expected standardization as FN-DSA in 2025.  Included here labelled
# as "pending standardization" for academic comparison due to its
# uniquely compact signatures.
SIG_PARAMS = {
    # FIPS 204 -- ML-DSA
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
    # FIPS 205 -- SLH-DSA (SPHINCS+)
    "SLH-DSA-128s": {
        "public_key": 32,
        "secret_key": 64,
        "signature": 7856,
    },
    "SLH-DSA-128f": {
        "public_key": 32,
        "secret_key": 64,
        "signature": 17088,
    },
    "SLH-DSA-192s": {
        "public_key": 48,
        "secret_key": 96,
        "signature": 16224,
    },
    "SLH-DSA-256f": {
        "public_key": 64,
        "secret_key": 128,
        "signature": 49856,
    },
    # Falcon (pending FIPS standardization as FN-DSA)
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

# ECDSA (secp256k1) -- Bitcoin/Ethereum classical baseline
ECDSA_PARAMS = {
    "public_key": 33,  # compressed
    "signature": 72,   # DER-encoded
}

# Algorithms that support hybrid mode (Ed25519 + PQC)
# NOTE: This is a proof-of-concept concatenation approach without
# domain separation.  Production hybrid designs should follow
# composite signature standards (e.g., NIST SP 800-227).
HYBRIDABLE_SIGS = [
    "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
    "Falcon-512", "Falcon-1024",
]

# Subsets for categorization
FIPS_204_ALGOS = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]
FIPS_205_ALGOS = ["SLH-DSA-128s", "SLH-DSA-128f", "SLH-DSA-192s", "SLH-DSA-256f"]
FALCON_ALGOS = ["Falcon-512", "Falcon-1024"]


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
    # Mock verification: returns True only if signature matches mock_sign output.
    # NOTE: This ignores public_key intentionally for determinism.
    # Real cryptographic verification requires liboqs.
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
