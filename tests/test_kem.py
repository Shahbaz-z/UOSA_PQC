"""Tests for pqc_lib.kem – Kyber KEM wrapper."""

import pytest

from pqc_lib.kem import keygen, encaps, decaps, KEM_ALGORITHMS


@pytest.mark.parametrize("algorithm", KEM_ALGORITHMS)
class TestKEM:
    def test_keygen_returns_bytes(self, algorithm: str):
        kp = keygen(algorithm)
        assert isinstance(kp.public_key, bytes)
        assert isinstance(kp.secret_key, bytes)
        assert len(kp.public_key) > 0
        assert len(kp.secret_key) > 0

    def test_keygen_timing(self, algorithm: str):
        kp = keygen(algorithm)
        assert kp.keygen_time_ms >= 0

    def test_encaps_decaps_roundtrip(self, algorithm: str):
        kp = keygen(algorithm)
        enc = encaps(algorithm, kp.public_key)
        dec = decaps(algorithm, kp.secret_key, enc.ciphertext)
        assert enc.shared_secret == dec.shared_secret

    def test_ciphertext_size(self, algorithm: str):
        kp = keygen(algorithm)
        enc = encaps(algorithm, kp.public_key)
        assert len(enc.ciphertext) > 0

    def test_shared_secret_length(self, algorithm: str):
        kp = keygen(algorithm)
        enc = encaps(algorithm, kp.public_key)
        assert len(enc.shared_secret) == 32


def test_invalid_algorithm():
    with pytest.raises(ValueError, match="Unknown KEM algorithm"):
        keygen("NotAnAlgorithm")
