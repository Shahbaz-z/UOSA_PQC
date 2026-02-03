"""Tests for pqc_lib.kem -- ML-KEM (FIPS 203) wrapper."""

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


def test_kyber_draft_names_removed():
    """Kyber draft names should not be in the algorithm list (ML-KEM only)."""
    for algo in KEM_ALGORITHMS:
        assert not algo.startswith("Kyber"), f"Draft name {algo} found; use ML-KEM instead"


class TestKEMNegative:
    """Negative test cases."""

    def test_different_keypairs_different_secrets(self):
        kp1 = keygen("ML-KEM-512")
        kp2 = keygen("ML-KEM-512")
        enc = encaps("ML-KEM-512", kp1.public_key)
        dec_wrong = decaps("ML-KEM-512", kp2.secret_key, enc.ciphertext)
        assert isinstance(dec_wrong.shared_secret, bytes)
        assert len(dec_wrong.shared_secret) == 32

    def test_all_ml_kem_variants_present(self):
        """All three ML-KEM security levels should be available."""
        assert "ML-KEM-512" in KEM_ALGORITHMS
        assert "ML-KEM-768" in KEM_ALGORITHMS
        assert "ML-KEM-1024" in KEM_ALGORITHMS
        assert len(KEM_ALGORITHMS) == 3
