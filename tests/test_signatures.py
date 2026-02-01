"""Tests for pqc_lib.signatures – Dilithium / Ed25519 / Hybrid wrapper."""

import pytest

from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from pqc_lib.mock import SIG_PARAMS, ED25519_PARAMS


# Filter to non-hybrid algorithms for basic tests
BASIC_ALGOS = [a for a in SIG_ALGORITHMS if not a.startswith("Hybrid")]
HYBRID_ALGOS = [a for a in SIG_ALGORITHMS if a.startswith("Hybrid")]


@pytest.mark.parametrize("algorithm", BASIC_ALGOS)
class TestBasicSignatures:
    def test_keygen(self, algorithm: str):
        kp = sign_keygen(algorithm)
        assert isinstance(kp.public_key, bytes)
        assert len(kp.public_key) > 0

    def test_sign_verify_roundtrip(self, algorithm: str):
        kp = sign_keygen(algorithm)
        msg = b"test message for signing"
        sr = sign(algorithm, kp.secret_key, msg, kp)
        vr = verify(algorithm, kp.public_key, msg, sr.signature, kp)
        assert vr.valid is True

    def test_signature_size_matches_spec(self, algorithm: str):
        kp = sign_keygen(algorithm)
        sr = sign(algorithm, kp.secret_key, b"size check", kp)
        if algorithm == "Ed25519":
            expected = ED25519_PARAMS["signature"]
        else:
            expected = SIG_PARAMS[algorithm]["signature"]
        assert sr.signature_size == expected


@pytest.mark.parametrize("algorithm", HYBRID_ALGOS)
class TestHybridSignatures:
    def test_keygen_has_both_keys(self, algorithm: str):
        kp = sign_keygen(algorithm)
        assert kp.ed25519_pk is not None
        assert kp.pqc_pk is not None
        # Combined public key = ed25519 pk + pqc pk
        assert kp.public_key == kp.ed25519_pk + kp.pqc_pk

    def test_sign_verify_roundtrip(self, algorithm: str):
        kp = sign_keygen(algorithm)
        msg = b"hybrid test message"
        sr = sign(algorithm, kp.secret_key, msg, kp)
        vr = verify(algorithm, kp.public_key, msg, sr.signature, kp)
        assert vr.valid is True

    def test_hybrid_signature_is_concatenation(self, algorithm: str):
        pqc_algo = algorithm.replace("Hybrid-Ed25519+", "")
        kp = sign_keygen(algorithm)
        sr = sign(algorithm, kp.secret_key, b"concat check", kp)
        expected_size = ED25519_PARAMS["signature"] + SIG_PARAMS[pqc_algo]["signature"]
        assert sr.signature_size == expected_size


def test_invalid_algorithm():
    with pytest.raises(ValueError, match="Unknown signature algorithm"):
        sign_keygen("NotAnAlgorithm")
