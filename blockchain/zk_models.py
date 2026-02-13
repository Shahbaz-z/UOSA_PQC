"""Zero-knowledge proof models for blockchain quantum resistance analysis.

Models the block-space and gas-cost impact of ZK-STARK and ZK-SNARK proof
systems on blockchain throughput, with focus on quantum resistance properties.

Key distinction:
- **ZK-STARKs** are quantum-resistant (hash-based, no elliptic curves)
- **ZK-SNARKs** (pairing-based like Groth16) are NOT quantum-resistant
  because they rely on elliptic-curve pairings vulnerable to Shor's algorithm
- **PLONK/KZG** SNARKs use polynomial commitments that are also vulnerable

This module enables comparison of:
1. ZK proof sizes vs PQC signature sizes
2. Verification gas costs on Ethereum
3. Throughput impact when transactions include ZK proofs
4. Quantum resistance properties across proof systems

Sources:
- StarkWare STARK proof sizes: https://starkware.co/
- Ethereum EIP-197 (bn128 precompiles) for SNARK verification gas
- ethSTARK documentation for on-chain verification costs
- Groth16 proof structure: 3 group elements (~128 bytes on bn128)
- PLONK proof structure: ~400-600 bytes depending on circuit
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# ZK Proof system parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZKProofParams:
    """Parameters for a zero-knowledge proof system."""
    name: str
    proof_bytes: int
    verification_gas: int           # Ethereum gas cost for on-chain verification
    quantum_resistant: bool
    trusted_setup: bool             # True if requires trusted ceremony
    proof_family: str               # "STARK", "SNARK", or "Hybrid"
    description: str
    security_bits: int              # Classical security level in bits
    # Typical proof generation time (ms) for a simple circuit (~1000 constraints)
    prover_time_ms: float


# Proof system catalog with realistic parameters
# Sources:
# - Groth16: 3 G1 + 1 G2 elements on bn128 = 128 bytes, ~200k gas verification
# - PLONK: ~560 bytes, ~300k gas (KZG commitment scheme)
# - Halo2: ~4-5 KB, recursive-friendly, no trusted setup for inner proofs
# - STARK (ethSTARK): 40-200 KB depending on trace length, ~1-5M gas
# - STARK (Stone/Cairo): ~50-100 KB for typical programs
ZK_PROOF_SYSTEMS: Dict[str, ZKProofParams] = {
    "Groth16": ZKProofParams(
        name="Groth16",
        proof_bytes=128,
        verification_gas=200_000,
        quantum_resistant=False,
        trusted_setup=True,
        proof_family="SNARK",
        description=(
            "Most compact SNARK. 3 group elements on bn128. "
            "Requires per-circuit trusted setup ceremony. "
            "NOT quantum-resistant (pairing-based)."
        ),
        security_bits=128,
        prover_time_ms=1500.0,
    ),
    "PLONK": ZKProofParams(
        name="PLONK",
        proof_bytes=560,
        verification_gas=300_000,
        quantum_resistant=False,
        trusted_setup=True,  # Universal trusted setup (reusable)
        proof_family="SNARK",
        description=(
            "Universal SNARK with reusable trusted setup. "
            "Larger proofs than Groth16 but more flexible. "
            "NOT quantum-resistant (KZG polynomial commitments)."
        ),
        security_bits=128,
        prover_time_ms=2000.0,
    ),
    "Halo2": ZKProofParams(
        name="Halo2",
        proof_bytes=4_800,
        verification_gas=500_000,
        quantum_resistant=False,
        trusted_setup=False,  # IPA commitment -- no trusted setup
        proof_family="SNARK",
        description=(
            "Recursive SNARK using IPA commitments (no trusted setup). "
            "Larger proofs but enables proof aggregation. "
            "NOT quantum-resistant (elliptic-curve based IPA)."
        ),
        security_bits=128,
        prover_time_ms=3000.0,
    ),
    "STARK-S": ZKProofParams(
        name="STARK-S",
        proof_bytes=45_000,
        verification_gas=1_200_000,
        quantum_resistant=True,
        trusted_setup=False,
        proof_family="STARK",
        description=(
            "Small STARK proof (optimized, e.g., Stone prover with DEEP-FRI). "
            "Transparent setup, quantum-resistant (hash-based). "
            "Used by StarkNet for L2 transaction batches."
        ),
        security_bits=128,
        prover_time_ms=5000.0,
    ),
    "STARK-L": ZKProofParams(
        name="STARK-L",
        proof_bytes=200_000,
        verification_gas=5_000_000,
        quantum_resistant=True,
        trusted_setup=False,
        proof_family="STARK",
        description=(
            "Large STARK proof (conservative parameters, longer FRI queries). "
            "Maximum security margins at cost of proof size. "
            "Transparent and quantum-resistant."
        ),
        security_bits=256,
        prover_time_ms=15000.0,
    ),
}

# Subset lists for convenience
SNARK_SYSTEMS = [k for k, v in ZK_PROOF_SYSTEMS.items() if v.proof_family == "SNARK"]
STARK_SYSTEMS = [k for k, v in ZK_PROOF_SYSTEMS.items() if v.proof_family == "STARK"]
QR_PROOF_SYSTEMS = [k for k, v in ZK_PROOF_SYSTEMS.items() if v.quantum_resistant]

# ---------------------------------------------------------------------------
# Ethereum parameters (reuse from solana_model but keep self-contained)
# ---------------------------------------------------------------------------
ETH_BLOCK_GAS_LIMIT_DEFAULT = 30_000_000
ETH_BLOCK_TIME_MS_DEFAULT = 12_000
ETH_BASE_TX_GAS = 21_000
ETH_CALLDATA_GAS_PER_BYTE = 16

# ---------------------------------------------------------------------------
# Analysis dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ZKProofAnalysis:
    """Analysis of a ZK proof system's impact on blockchain throughput."""
    proof_system: str
    proof_bytes: int
    verification_gas: int
    total_tx_gas: int
    txs_per_block: int
    throughput_tps: float
    quantum_resistant: bool
    trusted_setup: bool
    proof_family: str
    # Comparison metrics
    relative_to_ecdsa: float        # vs ECDSA baseline (signature-only tx)
    gas_overhead_vs_ecdsa: float    # additional gas vs ECDSA tx


@dataclass
class ZKvsSignatureComparison:
    """Comparison of a ZK proof system against a signature scheme."""
    zk_system: str
    signature_scheme: str
    zk_proof_bytes: int
    signature_bytes: int
    size_ratio: float               # zk / sig size
    zk_tx_gas: int
    sig_tx_gas: int
    gas_ratio: float                # zk / sig gas
    zk_quantum_resistant: bool
    sig_quantum_resistant: bool


# ---------------------------------------------------------------------------
# ECDSA baseline for Ethereum (for comparison)
# ---------------------------------------------------------------------------
ECDSA_SIG_BYTES = 72   # DER-encoded secp256k1
ECDSA_PK_BYTES = 33    # Compressed public key
ECDSA_CALLDATA_BYTES = ECDSA_SIG_BYTES + ECDSA_PK_BYTES + 120  # + base overhead
ECDSA_TX_GAS = ETH_BASE_TX_GAS + (ECDSA_CALLDATA_BYTES * ETH_CALLDATA_GAS_PER_BYTE)


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_zk_proof_throughput(
    proof_system: str,
    block_gas_limit: int = ETH_BLOCK_GAS_LIMIT_DEFAULT,
    block_time_ms: int = ETH_BLOCK_TIME_MS_DEFAULT,
    base_tx_gas: int = ETH_BASE_TX_GAS,
    calldata_gas_per_byte: int = ETH_CALLDATA_GAS_PER_BYTE,
    include_calldata_cost: bool = True,
) -> ZKProofAnalysis:
    """Analyze throughput impact of a ZK proof system on Ethereum.

    For ZK proofs, the cost model is:
    - Base intrinsic gas (21,000)
    - Calldata gas for the proof bytes (16 gas/byte if posted on-chain)
    - Verification gas (precompile or EVM execution)

    Args:
        proof_system: Name of proof system (must be in ZK_PROOF_SYSTEMS)
        block_gas_limit: Ethereum block gas limit
        block_time_ms: Block time in milliseconds
        base_tx_gas: Base intrinsic gas per transaction
        calldata_gas_per_byte: Gas per byte of calldata
        include_calldata_cost: If True, add calldata cost for proof bytes.
            Set False to model proof verification via precompile only.
    """
    if proof_system not in ZK_PROOF_SYSTEMS:
        raise ValueError(
            f"Unknown proof system: {proof_system}. "
            f"Valid systems: {list(ZK_PROOF_SYSTEMS.keys())}"
        )

    params = ZK_PROOF_SYSTEMS[proof_system]

    # Total gas per transaction with ZK proof
    calldata_gas = (params.proof_bytes * calldata_gas_per_byte) if include_calldata_cost else 0
    total_tx_gas = base_tx_gas + calldata_gas + params.verification_gas

    txs_per_block = block_gas_limit // total_tx_gas
    tps = txs_per_block / (block_time_ms / 1000)

    # ECDSA baseline
    ecdsa_txs = block_gas_limit // ECDSA_TX_GAS

    return ZKProofAnalysis(
        proof_system=proof_system,
        proof_bytes=params.proof_bytes,
        verification_gas=params.verification_gas,
        total_tx_gas=total_tx_gas,
        txs_per_block=txs_per_block,
        throughput_tps=round(tps, 2),
        quantum_resistant=params.quantum_resistant,
        trusted_setup=params.trusted_setup,
        proof_family=params.proof_family,
        relative_to_ecdsa=round(txs_per_block / ecdsa_txs, 4) if ecdsa_txs > 0 else 0,
        gas_overhead_vs_ecdsa=round((total_tx_gas - ECDSA_TX_GAS) / ECDSA_TX_GAS, 4),
    )


def compare_all_zk_proofs(
    block_gas_limit: int = ETH_BLOCK_GAS_LIMIT_DEFAULT,
    block_time_ms: int = ETH_BLOCK_TIME_MS_DEFAULT,
    include_calldata_cost: bool = True,
) -> List[ZKProofAnalysis]:
    """Analyze all ZK proof systems for Ethereum throughput impact."""
    return [
        analyze_zk_proof_throughput(
            system, block_gas_limit, block_time_ms,
            include_calldata_cost=include_calldata_cost,
        )
        for system in ZK_PROOF_SYSTEMS
    ]


def compare_zk_vs_signature(
    proof_system: str,
    signature_scheme: str,
    sig_bytes: int,
    sig_pk_bytes: int,
    sig_quantum_resistant: bool,
    base_tx_overhead_bytes: int = 120,
    calldata_gas_per_byte: int = ETH_CALLDATA_GAS_PER_BYTE,
    base_tx_gas: int = ETH_BASE_TX_GAS,
) -> ZKvsSignatureComparison:
    """Compare a ZK proof system against a signature scheme on Ethereum gas model.

    Args:
        proof_system: Name of ZK proof system
        signature_scheme: Name of signature scheme (e.g., "ML-DSA-65")
        sig_bytes: Signature size in bytes
        sig_pk_bytes: Public key size in bytes
        sig_quantum_resistant: Whether the signature scheme is quantum-resistant
        base_tx_overhead_bytes: Non-signature/proof calldata overhead
        calldata_gas_per_byte: Gas per byte of calldata
        base_tx_gas: Base intrinsic gas per transaction
    """
    if proof_system not in ZK_PROOF_SYSTEMS:
        raise ValueError(
            f"Unknown proof system: {proof_system}. "
            f"Valid systems: {list(ZK_PROOF_SYSTEMS.keys())}"
        )

    params = ZK_PROOF_SYSTEMS[proof_system]

    # ZK proof transaction gas
    zk_calldata = params.proof_bytes * calldata_gas_per_byte
    zk_tx_gas = base_tx_gas + zk_calldata + params.verification_gas

    # Signature transaction gas
    sig_calldata = (sig_bytes + sig_pk_bytes + base_tx_overhead_bytes) * calldata_gas_per_byte
    sig_tx_gas = base_tx_gas + sig_calldata

    return ZKvsSignatureComparison(
        zk_system=proof_system,
        signature_scheme=signature_scheme,
        zk_proof_bytes=params.proof_bytes,
        signature_bytes=sig_bytes,
        size_ratio=round(params.proof_bytes / sig_bytes, 2) if sig_bytes > 0 else 0,
        zk_tx_gas=zk_tx_gas,
        sig_tx_gas=sig_tx_gas,
        gas_ratio=round(zk_tx_gas / sig_tx_gas, 2) if sig_tx_gas > 0 else 0,
        zk_quantum_resistant=params.quantum_resistant,
        sig_quantum_resistant=sig_quantum_resistant,
    )


def build_zk_vs_signatures_table(
    block_gas_limit: int = ETH_BLOCK_GAS_LIMIT_DEFAULT,
    block_time_ms: int = ETH_BLOCK_TIME_MS_DEFAULT,
) -> List[dict]:
    """Build a comparison table of ZK proofs vs key PQC signatures on Ethereum.

    Returns a list of dicts suitable for DataFrame construction, comparing
    throughput across ZK proof systems and selected signature schemes.
    """
    from blockchain.solana_model import (
        SIGNATURE_SIZES, PUBLIC_KEY_SIZES,
        analyze_ethereum_block_space,
    )

    rows = []

    # ZK proof systems
    for system_name, params in ZK_PROOF_SYSTEMS.items():
        analysis = analyze_zk_proof_throughput(
            system_name, block_gas_limit, block_time_ms
        )
        rows.append({
            "Scheme": system_name,
            "Type": f"ZK-{params.proof_family}",
            "Size (B)": params.proof_bytes,
            "Tx Gas": analysis.total_tx_gas,
            "Txs/Block": analysis.txs_per_block,
            "TPS": analysis.throughput_tps,
            "Quantum Resistant": "Yes" if params.quantum_resistant else "No",
            "Trusted Setup": "Yes" if params.trusted_setup else "No",
        })

    # Key signature schemes for comparison
    sig_schemes = ["ECDSA", "Falcon-512", "ML-DSA-44", "ML-DSA-65", "SLH-DSA-128s"]
    classical_sigs = {"ECDSA"}

    for sig in sig_schemes:
        if sig in SIGNATURE_SIZES:
            analysis = analyze_ethereum_block_space(
                sig, block_gas_limit=block_gas_limit,
                block_time_ms=block_time_ms,
            )
            rows.append({
                "Scheme": sig,
                "Type": "Signature",
                "Size (B)": SIGNATURE_SIZES[sig] + PUBLIC_KEY_SIZES[sig],
                "Tx Gas": analysis.txs_per_block and (block_gas_limit // analysis.txs_per_block),
                "Txs/Block": analysis.txs_per_block,
                "TPS": analysis.throughput_tps,
                "Quantum Resistant": "No" if sig in classical_sigs else "Yes",
                "Trusted Setup": "No",
            })

    return rows
