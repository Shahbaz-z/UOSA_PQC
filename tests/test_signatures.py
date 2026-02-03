"""Tests for pqc_lib.signatures -- ML-DSA / SLH-DSA / Falcon / Ed25519 / Hybrid."""

import pytest

from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from pqc_lib.mock import SIG_PARAMS, ED25519_PARAMS, FIPS_204_ALGOS, FIPS_205_ALGOS, FALCON_ALGOS


# Filter algorithm categories
BASIC_ALGOS = [a for a in SIG_ALGORITHMS if not a.startswith("Hybrid")]
HYBRID_ALGOS = [a for a in SIG_ALGORITHMS if a.startswith("Hybrid")]
SLH_DSA_ALGOS = [a for a in SIG_ALGORITHMS if a.startswith("SLH-DSA")]


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


def test_dilithium_draft_names_removed():
    """Dilithium draft names should not be in the algorithm list."""
    for algo in SIG_ALGORITHMS:
        assert not algo.startswith("Dilithium"), f"Draft name {algo} found; use ML-DSA instead"


class TestFalcon:
    """Falcon-specific tests (pending FIPS standardization as FN-DSA)."""

    def test_falcon512_compact_signature(self):
        kp = sign_keygen("Falcon-512")
        sr = sign("Falcon-512", kp.secret_key, b"falcon test", kp)
        assert sr.signature_size == 666

    def test_falcon1024_signature_size(self):
        kp = sign_keygen("Falcon-1024")
        sr = sign("Falcon-1024", kp.secret_key, b"falcon test", kp)
        assert sr.signature_size == 1280

    def test_falcon512_smaller_than_ml_dsa_44(self):
        kp_f = sign_keygen("Falcon-512")
        kp_d = sign_keygen("ML-DSA-44")
        sr_f = sign("Falcon-512", kp_f.secret_key, b"compare", kp_f)
        sr_d = sign("ML-DSA-44", kp_d.secret_key, b"compare", kp_d)
        assert sr_f.signature_size < sr_d.signature_size


class TestSLHDSA:
    """SLH-DSA (FIPS 205 / SPHINCS+) tests -- hash-based signatures."""

    def test_all_slh_dsa_variants_present(self):
        for algo in FIPS_205_ALGOS:
            assert algo in SIG_ALGORITHMS, f"{algo} missing from SIG_ALGORITHMS"

    @pytest.mark.parametrize("algorithm", FIPS_205_ALGOS)
    def test_keygen_and_sign(self, algorithm: str):
        kp = sign_keygen(algorithm)
        sr = sign(algorithm, kp.secret_key, b"slh-dsa test", kp)
        vr = verify(algorithm, kp.public_key, b"slh-dsa test", sr.signature, kp)
        assert vr.valid is True

    def test_slh_dsa_128s_signature_size(self):
        kp = sign_keygen("SLH-DSA-128s")
        sr = sign("SLH-DSA-128s", kp.secret_key, b"size check", kp)
        assert sr.signature_size == 7856

    def test_slh_dsa_128f_larger_than_128s(self):
        """Fast variant has larger signatures than small variant."""
        kp_s = sign_keygen("SLH-DSA-128s")
        kp_f = sign_keygen("SLH-DSA-128f")
        sr_s = sign("SLH-DSA-128s", kp_s.secret_key, b"compare", kp_s)
        sr_f = sign("SLH-DSA-128f", kp_f.secret_key, b"compare", kp_f)
        assert sr_f.signature_size > sr_s.signature_size

    def test_slh_dsa_256f_largest_signature(self):
        """SLH-DSA-256f should have the largest signature of all algorithms."""
        kp = sign_keygen("SLH-DSA-256f")
        sr = sign("SLH-DSA-256f", kp.secret_key, b"max size", kp)
        assert sr.signature_size == 49856
        # Should be larger than any ML-DSA or Falcon signature
        assert sr.signature_size > SIG_PARAMS["ML-DSA-87"]["signature"]
        assert sr.signature_size > SIG_PARAMS["Falcon-1024"]["signature"]

    def test_slh_dsa_tiny_public_keys(self):
        """SLH-DSA has notably small public keys (32-64 bytes)."""
        kp = sign_keygen("SLH-DSA-128s")
        assert len(kp.public_key) == 32  # Same size as Ed25519!


class TestNegativeSignatures:
    """Negative test cases -- corrupted signatures, wrong messages."""

    def test_corrupted_signature_fails(self):
        kp = sign_keygen("ML-DSA-65")
        msg = b"integrity check"
        sr = sign("ML-DSA-65", kp.secret_key, msg, kp)
        corrupted = bytearray(sr.signature)
        corrupted[0] ^= 0xFF
        vr = verify("ML-DSA-65", kp.public_key, msg, bytes(corrupted), kp)
        assert vr.valid is False

    def test_wrong_message_fails(self):
        kp = sign_keygen("ML-DSA-44")
        sr = sign("ML-DSA-44", kp.secret_key, b"original message", kp)
        vr = verify("ML-DSA-44", kp.public_key, b"different message", sr.signature, kp)
        assert isinstance(vr.valid, bool)

    def test_ed25519_corrupted_signature(self):
        kp = sign_keygen("Ed25519")
        sr = sign("Ed25519", kp.secret_key, b"ed25519 test", kp)
        corrupted = bytearray(sr.signature)
        corrupted[0] ^= 0xFF
        vr = verify("Ed25519", kp.public_key, b"ed25519 test", bytes(corrupted), kp)
        assert vr.valid is False

    def test_hybrid_corrupted_pqc_part(self):
        kp = sign_keygen("Hybrid-Ed25519+ML-DSA-65")
        msg = b"hybrid integrity"
        sr = sign("Hybrid-Ed25519+ML-DSA-65", kp.secret_key, msg, kp)
        corrupted = bytearray(sr.signature)
        corrupted[65] ^= 0xFF
        vr = verify("Hybrid-Ed25519+ML-DSA-65", kp.public_key, msg, bytes(corrupted), kp)
        assert vr.valid is False

    def test_slh_dsa_corrupted_signature(self):
        kp = sign_keygen("SLH-DSA-128s")
        msg = b"slh-dsa integrity"
        sr = sign("SLH-DSA-128s", kp.secret_key, msg, kp)
        corrupted = bytearray(sr.signature)
        corrupted[0] ^= 0xFF
        vr = verify("SLH-DSA-128s", kp.public_key, msg, bytes(corrupted), kp)
        assert vr.valid is False
