"""PQC library wrappers for ML-KEM (FIPS 203) and PQC signatures (FIPS 204/205)."""

from pqc_lib.kem import keygen as kem_keygen, encaps, decaps, KEM_ALGORITHMS
from pqc_lib.signatures import (
    sign_keygen,
    sign,
    verify,
    SIG_ALGORITHMS,
)
from pqc_lib.mock import MOCK_MODE

__all__ = [
    "kem_keygen",
    "encaps",
    "decaps",
    "sign_keygen",
    "sign",
    "verify",
    "KEM_ALGORITHMS",
    "SIG_ALGORITHMS",
    "MOCK_MODE",
]
