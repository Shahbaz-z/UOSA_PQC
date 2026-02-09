"""PQC signature wrapper with automatic mock fallback.

Supports NIST-standardized algorithms:
  - ML-DSA-44/65/87  (FIPS 204, lattice-based, formerly "Dilithium")
  - SLH-DSA-128s/128f/192s/256f  (FIPS 205, hash-based, formerly "SPHINCS+")
  - Falcon-512/1024  (pending FIPS as FN-DSA, lattice/NTRU-based)
  - Ed25519 via PyNaCl (classical, not quantum-resistant)

Hybrid mode concatenates Ed25519 + PQC signatures (sign-with-both,
verify-both).  This is a proof-of-concept approach without domain
separation; production hybrid designs should follow composite
signature standards (e.g., NIST SP 800-227).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pqc_lib.mock import MOCK_MODE, SIG_PARAMS, ED25519_PARAMS, HYBRIDABLE_SIGS
from pqc_lib.utils import timed_call

if not MOCK_MODE:
    import oqs
    try:
        from nacl.signing import SigningKey, VerifyKey
        _HAS_NACL = True
    except ImportError:
        _HAS_NACL = False
else:
    _HAS_NACL = False

SIG_ALGORITHMS = list(SIG_PARAMS.keys()) + ["Ed25519"]

# Add hybrid algorithms for all hybridable PQC sigs
HYBRID_ALGORITHMS = [f"Hybrid-Ed25519+{s}" for s in HYBRIDABLE_SIGS]
SIG_ALGORITHMS += HYBRID_ALGORITHMS


@dataclass
class SigKeypair:
    algorithm: str
    public_key: bytes
    secret_key: bytes
    keygen_time_ms: float
    peak_memory_kb: float
    # For hybrid: store both keypairs
    ed25519_pk: Optional[bytes] = None
    ed25519_sk: Optional[bytes] = None
    pqc_pk: Optional[bytes] = None
    pqc_sk: Optional[bytes] = None


@dataclass
class SignResult:
    algorithm: str
    signature: bytes
    signature_size: int
    time_ms: float
    peak_memory_kb: float


@dataclass
class VerifyResult:
    algorithm: str
    valid: bool
    time_ms: float
    peak_memory_kb: float


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _ed25519_keygen():
    if MOCK_MODE or not _HAS_NACL:
        from pqc_lib.mock import mock_ed25519_keygen
        return mock_ed25519_keygen()
    sk_obj = SigningKey.generate()
    pk_obj = sk_obj.verify_key
    return bytes(pk_obj), bytes(sk_obj)


def _ed25519_sign(secret_key: bytes, message: bytes) -> bytes:
    if MOCK_MODE or not _HAS_NACL:
        from pqc_lib.mock import mock_ed25519_sign
        return mock_ed25519_sign(secret_key, message)
    sk_obj = SigningKey(secret_key[:ED25519_PARAMS["public_key"]])
    signed = sk_obj.sign(message)
    return signed.signature


def _ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if MOCK_MODE or not _HAS_NACL:
        from pqc_lib.mock import mock_ed25519_verify
        return mock_ed25519_verify(public_key, message, signature)
    try:
        vk = VerifyKey(public_key)
        vk.verify(message, signature)
        return True
    except Exception:
        return False


def _pqc_keygen(algorithm: str):
    """Generate keypair for any PQC algorithm in SIG_PARAMS."""
    if MOCK_MODE:
        from pqc_lib.mock import mock_sig_keygen
        return mock_sig_keygen(algorithm)
    sig = oqs.Signature(algorithm)
    pk = sig.generate_keypair()
    sk = sig.export_secret_key()
    return pk, sk


def _pqc_sign(algorithm: str, secret_key: bytes, message: bytes) -> bytes:
    """Sign with any PQC algorithm in SIG_PARAMS."""
    if MOCK_MODE:
        from pqc_lib.mock import mock_sign
        return mock_sign(algorithm, secret_key, message)
    sig = oqs.Signature(algorithm, secret_key)
    return sig.sign(message)


def _pqc_verify(algorithm: str, public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify with any PQC algorithm in SIG_PARAMS."""
    if MOCK_MODE:
        from pqc_lib.mock import mock_verify
        return mock_verify(algorithm, public_key, message, signature)
    sig = oqs.Signature(algorithm)
    return sig.verify(message, signature, public_key)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def sign_keygen(algorithm: str) -> SigKeypair:
    """Generate a signature keypair."""
    if algorithm == "Ed25519":
        tr = timed_call(_ed25519_keygen)
        pk, sk = tr.result
        return SigKeypair(
            algorithm=algorithm,
            public_key=pk,
            secret_key=sk,
            keygen_time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    if algorithm.startswith("Hybrid-Ed25519+"):
        pqc_algo = algorithm.replace("Hybrid-Ed25519+", "")
        tr_ed = timed_call(_ed25519_keygen)
        ed_pk, ed_sk = tr_ed.result
        tr_pqc = timed_call(_pqc_keygen, pqc_algo)
        pqc_pk, pqc_sk = tr_pqc.result
        return SigKeypair(
            algorithm=algorithm,
            public_key=ed_pk + pqc_pk,
            secret_key=ed_sk + pqc_sk,
            keygen_time_ms=tr_ed.elapsed_ms + tr_pqc.elapsed_ms,
            peak_memory_kb=max(tr_ed.peak_memory_kb, tr_pqc.peak_memory_kb),
            ed25519_pk=ed_pk,
            ed25519_sk=ed_sk,
            pqc_pk=pqc_pk,
            pqc_sk=pqc_sk,
        )

    if algorithm in SIG_PARAMS:
        tr = timed_call(_pqc_keygen, algorithm)
        pk, sk = tr.result
        return SigKeypair(
            algorithm=algorithm,
            public_key=pk,
            secret_key=sk,
            keygen_time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    raise ValueError(f"Unknown signature algorithm: {algorithm}")


def sign(algorithm: str, secret_key: bytes, message: bytes, keypair: Optional[SigKeypair] = None) -> SignResult:
    """Sign *message*."""
    if algorithm == "Ed25519":
        tr = timed_call(_ed25519_sign, secret_key, message)
        return SignResult(
            algorithm=algorithm,
            signature=tr.result,
            signature_size=len(tr.result),
            time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    if algorithm.startswith("Hybrid-Ed25519+"):
        pqc_algo = algorithm.replace("Hybrid-Ed25519+", "")
        if keypair is not None:
            ed_sk = keypair.ed25519_sk
            pqc_sk = keypair.pqc_sk
        else:
            ed_sk_len = ED25519_PARAMS["secret_key"]
            ed_sk = secret_key[:ed_sk_len]
            pqc_sk = secret_key[ed_sk_len:]

        tr_ed = timed_call(_ed25519_sign, ed_sk, message)
        tr_pqc = timed_call(_pqc_sign, pqc_algo, pqc_sk, message)
        combined = tr_ed.result + tr_pqc.result
        return SignResult(
            algorithm=algorithm,
            signature=combined,
            signature_size=len(combined),
            time_ms=tr_ed.elapsed_ms + tr_pqc.elapsed_ms,
            peak_memory_kb=max(tr_ed.peak_memory_kb, tr_pqc.peak_memory_kb),
        )

    if algorithm in SIG_PARAMS:
        tr = timed_call(_pqc_sign, algorithm, secret_key, message)
        return SignResult(
            algorithm=algorithm,
            signature=tr.result,
            signature_size=len(tr.result),
            time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    raise ValueError(f"Unknown signature algorithm: {algorithm}")


def verify(
    algorithm: str,
    public_key: bytes,
    message: bytes,
    signature: bytes,
    keypair: Optional[SigKeypair] = None,
) -> VerifyResult:
    """Verify *signature* over *message*."""
    if algorithm == "Ed25519":
        tr = timed_call(_ed25519_verify, public_key, message, signature)
        return VerifyResult(
            algorithm=algorithm,
            valid=tr.result,
            time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    if algorithm.startswith("Hybrid-Ed25519+"):
        pqc_algo = algorithm.replace("Hybrid-Ed25519+", "")
        ed_sig_len = ED25519_PARAMS["signature"]

        if keypair is not None:
            ed_pk = keypair.ed25519_pk
            pqc_pk = keypair.pqc_pk
        else:
            ed_pk_len = ED25519_PARAMS["public_key"]
            ed_pk = public_key[:ed_pk_len]
            pqc_pk = public_key[ed_pk_len:]

        ed_sig = signature[:ed_sig_len]
        pqc_sig = signature[ed_sig_len:]

        tr_ed = timed_call(_ed25519_verify, ed_pk, message, ed_sig)
        tr_pqc = timed_call(_pqc_verify, pqc_algo, pqc_pk, message, pqc_sig)
        return VerifyResult(
            algorithm=algorithm,
            valid=tr_ed.result and tr_pqc.result,
            time_ms=tr_ed.elapsed_ms + tr_pqc.elapsed_ms,
            peak_memory_kb=max(tr_ed.peak_memory_kb, tr_pqc.peak_memory_kb),
        )

    if algorithm in SIG_PARAMS:
        tr = timed_call(_pqc_verify, algorithm, public_key, message, signature)
        return VerifyResult(
            algorithm=algorithm,
            valid=tr.result,
            time_ms=tr.elapsed_ms,
            peak_memory_kb=tr.peak_memory_kb,
        )

    raise ValueError(f"Unknown signature algorithm: {algorithm}")
