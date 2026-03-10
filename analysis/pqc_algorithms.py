"""PQC algorithm parameters — single source of truth for all chain analyses.

Signature sizes, public key sizes, estimated verification gas costs,
and security levels for NIST PQC candidates vs ECDSA/BLS baselines.

References:
    - NIST PQC Round 3: https://csrc.nist.gov/projects/post-quantum-cryptography
    - FALCON spec: https://falcon-sign.info/
    - CRYSTALS-Dilithium: https://pq-crystals.org/dilithium/
    - SPHINCS+: https://sphincs.org/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class PQCAlgorithm:
    """Immutable record of a PQC (or classical) signature algorithm.

    Attributes:
        name: Human-readable algorithm name.
        sig_bytes: Signature size in bytes.
        pk_bytes: Public key size in bytes.
        security_level: NIST security level (1–5) or 'classical'.
        verify_gas_estimate: Estimated EVM gas for verification.
            Scaled from ecRecover (3000 gas) by relative verification time.
        family: Algorithm family for grouping (ecdsa, bls, falcon, dilithium, sphincs).
    """

    name: str
    sig_bytes: int
    pk_bytes: int
    security_level: str
    verify_gas_estimate: int
    family: str


# ── Algorithm catalogue ────────────────────────────────────────────
# Classical baselines
ECDSA = PQCAlgorithm(
    name="ECDSA (secp256k1)",
    sig_bytes=72,
    pk_bytes=33,
    security_level="~128-bit",
    verify_gas_estimate=3_000,
    family="ecdsa",
)

BLS_12_381 = PQCAlgorithm(
    name="BLS12-381",
    sig_bytes=96,
    pk_bytes=48,
    security_level="~128-bit",
    verify_gas_estimate=0,  # consensus layer, not EVM
    family="bls",
)

# FALCON
FALCON_512 = PQCAlgorithm(
    name="FALCON-512",
    sig_bytes=666,
    pk_bytes=897,
    security_level="NIST-1",
    verify_gas_estimate=10_000,
    family="falcon",
)

FALCON_1024 = PQCAlgorithm(
    name="FALCON-1024",
    sig_bytes=1_280,
    pk_bytes=1_793,
    security_level="NIST-5",
    verify_gas_estimate=18_000,
    family="falcon",
)

# CRYSTALS-Dilithium (ML-DSA)
DILITHIUM2 = PQCAlgorithm(
    name="Dilithium2 (ML-DSA-44)",
    sig_bytes=2_420,
    pk_bytes=1_312,
    security_level="NIST-2",
    verify_gas_estimate=15_000,
    family="dilithium",
)

DILITHIUM3 = PQCAlgorithm(
    name="Dilithium3 (ML-DSA-65)",
    sig_bytes=3_293,
    pk_bytes=1_952,
    security_level="NIST-3",
    verify_gas_estimate=22_000,
    family="dilithium",
)

DILITHIUM5 = PQCAlgorithm(
    name="Dilithium5 (ML-DSA-87)",
    sig_bytes=4_595,
    pk_bytes=2_592,
    security_level="NIST-5",
    verify_gas_estimate=35_000,
    family="dilithium",
)

# SPHINCS+ (SLH-DSA)
SPHINCS_128S = PQCAlgorithm(
    name="SPHINCS+-128s",
    sig_bytes=7_856,
    pk_bytes=32,
    security_level="NIST-1",
    verify_gas_estimate=100_000,
    family="sphincs",
)

SPHINCS_256S = PQCAlgorithm(
    name="SPHINCS+-256s",
    sig_bytes=29_792,
    pk_bytes=64,
    security_level="NIST-5",
    verify_gas_estimate=300_000,
    family="sphincs",
)


# Ordered list for iteration (baseline first, then by family)
ALL_ALGORITHMS: List[PQCAlgorithm] = [
    ECDSA,
    FALCON_512, FALCON_1024,
    DILITHIUM2, DILITHIUM3, DILITHIUM5,
    SPHINCS_128S, SPHINCS_256S,
]

PQC_ALGORITHMS: List[PQCAlgorithm] = [a for a in ALL_ALGORITHMS if a.family != "ecdsa"]

ALGORITHM_BY_NAME: Dict[str, PQCAlgorithm] = {a.name: a for a in ALL_ALGORITHMS}

# Family-based groupings for filtered runs
FAMILY_GROUPS: Dict[str, List[PQCAlgorithm]] = {}
for _alg in ALL_ALGORITHMS:
    FAMILY_GROUPS.setdefault(_alg.family, []).append(_alg)
