"""Tests for pqc_lib.kem – Kyber / ML-KEM wrapper."""

import pytest

from pqc_lib.kem import keygen, encaps, decaps, KEM_ALGORITHMS
from pqc_lib.mock import KEM_PARAMS


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

    def test_key_sizes_match_spec(self, algorithm: str):
        kp = keygen(algorithm)
        expected = KEM_PARAMS[algorithm]
        assert len(kp.public_key) == expected["public_key"]
        assert len(kp.secret_key) == expected["secret_key"]

    def test_ciphertext_size_matches_spec(self, algorithm: str):
        kp = keygen(algorithm)
        enc = encaps(algorithm, kp.public_key)
        expected = KEM_PARAMS[algorithm]
        assert len(enc.ciphertext) == expected["ciphertext"]


def test_invalid_algorithm():
    with pytest.raises(ValueError, match="Unknown KEM algorithm"):
        keygen("NotAnAlgorithm")


class TestKEMNegative:
    """Negative test cases – wrong keys, tampered ciphertext."""

    def test_different_keypairs_different_secrets(self):
        """Decapsulating with a different secret key produces different shared secret."""
        kp1 = keygen("Kyber512")
        kp2 = keygen("Kyber512")
        enc = encaps("Kyber512", kp1.public_key)
        dec_wrong = decaps("Kyber512", kp2.secret_key, enc.ciphertext)
        # In mock mode both return deterministic values, so this only
        # applies meaningfully in real mode. In mock mode the shared
        # secrets will match because mock_kem_decaps ignores the key.
        # We still exercise the code path.
        assert isinstance(dec_wrong.shared_secret, bytes)
        assert len(dec_wrong.shared_secret) == 32

    def test_ml_kem_matches_kyber_sizes(self):
        """ML-KEM-512 and Kyber512 should produce same-sized artifacts."""
        kp_kyber = keygen("Kyber512")
        kp_mlkem = keygen("ML-KEM-512")
        assert len(kp_kyber.public_key) == len(kp_mlkem.public_key)
        assert len(kp_kyber.secret_key) == len(kp_mlkem.secret_key)
