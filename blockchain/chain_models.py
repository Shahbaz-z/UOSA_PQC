"""Blockchain block-space model for PQC signature impact analysis.

Models the effect of replacing classical signatures with post-quantum
schemes on transaction throughput for Solana, Bitcoin, and Ethereum.

Assumptions and limitations (document in report):
- We model *signature contribution* to transaction size, not full
  transaction serialization.
- Base transaction overhead is approximated as a constant.
- Solana practical block size is ~6 MB (theoretical 32 MB).
  Configurable vote_tx_pct parameter models validator vote overhead
  (typically 70-80% of real block space).
- Bitcoin block weight limit is 4 MWU; SegWit witness discount applies.
  Supports both ECDSA and Schnorr (BIP 340 Taproot) baselines.
- Ethereum uses gas-based cost model. Configurable gas limit supports
  2024 baseline (30M) through 2026 target (180M).

Sources:
- Solana docs: https://docs.solana.com/developing/programming-model/transactions
- Bitcoin BIP 141 (SegWit): witness data counted at 1/4 weight
- Ethereum EVM: calldata costs 16 gas/non-zero byte, 4 gas/zero byte
- NIST PQC standards (FIPS 203/204/205) for signature sizes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# ---------------------------------------------------------------------------
# Signature & public-key sizes (bytes) -- NIST standards only
# ---------------------------------------------------------------------------
SIGNATURE_SIZES: Dict[str, int] = {
    # Classical baselines (not quantum-resistant)
    "Ed25519": 64,
    "ECDSA": 72,  # DER-encoded secp256k1 (Bitcoin/Ethereum baseline)
    "Schnorr": 64,  # BIP 340 (Bitcoin Taproot) - fixed size
    "BLS12-381": 96,  # BLS signature (two G1 points, Ethereum consensus)
    # FIPS 204 -- ML-DSA
    "ML-DSA-44": 2_420,
    "ML-DSA-65": 3_293,
    "ML-DSA-87": 4_595,
    # FIPS 205 -- SLH-DSA (SPHINCS+) - all 6 parameter sets
    "SLH-DSA-128s": 7_856,
    "SLH-DSA-128f": 17_088,
    "SLH-DSA-192s": 16_224,
    "SLH-DSA-192f": 35_664,
    "SLH-DSA-256s": 29_792,
    "SLH-DSA-256f": 49_856,
    # Falcon (pending FIPS as FN-DSA)
    "Falcon-512": 666,
    "Falcon-1024": 1_280,
    # Hybrid (Ed25519 + PQC)
    "Hybrid-Ed25519+ML-DSA-44": 64 + 2_420,
    "Hybrid-Ed25519+ML-DSA-65": 64 + 3_293,
    "Hybrid-Ed25519+ML-DSA-87": 64 + 4_595,
    "Hybrid-Ed25519+Falcon-512": 64 + 666,
    "Hybrid-Ed25519+Falcon-1024": 64 + 1_280,
}

PUBLIC_KEY_SIZES: Dict[str, int] = {
    "Ed25519": 32,
    "ECDSA": 33,  # compressed secp256k1
    "Schnorr": 32,  # BIP 340 x-only pubkey
    "BLS12-381": 48,  # BLS public key (one G1 point)
    "ML-DSA-44": 1_312,
    "ML-DSA-65": 1_952,
    "ML-DSA-87": 2_592,
    "SLH-DSA-128s": 32,
    "SLH-DSA-128f": 32,
    "SLH-DSA-192s": 48,
    "SLH-DSA-192f": 48,
    "SLH-DSA-256s": 64,
    "SLH-DSA-256f": 64,
    "Falcon-512": 897,
    "Falcon-1024": 1_793,
    "Hybrid-Ed25519+ML-DSA-44": 32 + 1_312,
    "Hybrid-Ed25519+ML-DSA-65": 32 + 1_952,
    "Hybrid-Ed25519+ML-DSA-87": 32 + 2_592,
    "Hybrid-Ed25519+Falcon-512": 32 + 897,
    "Hybrid-Ed25519+Falcon-1024": 32 + 1_793,
}

# Subsets for each chain (Solana uses Ed25519 baseline, Bitcoin/Ethereum use ECDSA)
SOLANA_SIG_TYPES = [k for k in SIGNATURE_SIZES if k not in ("ECDSA", "Schnorr")]
BITCOIN_SIG_TYPES = [k for k in SIGNATURE_SIZES if k != "Ed25519"]
ETHEREUM_SIG_TYPES = [k for k in SIGNATURE_SIZES if k not in ("Ed25519", "Schnorr")]

# ---------------------------------------------------------------------------
# Solana parameters
# ---------------------------------------------------------------------------
SOLANA_BLOCK_SIZE_BYTES = 6_000_000  # ~6 MB practical limit
SOLANA_SLOT_TIME_MS = 400  # target slot time
SOLANA_BASE_TX_OVERHEAD = 250  # accounts, instructions, blockhash

# Vote transaction overhead: 70-80% of Solana blocks are validator votes
# Source: https://docs.solana.com/consensus/tower-bft
SOLANA_VOTE_TX_PCT_DEFAULT = 0.0  # backwards-compatible default (no overhead)
SOLANA_VOTE_TX_PCT_REALISTIC = 0.70  # ~70% of block space is votes

# ---------------------------------------------------------------------------
# Bitcoin parameters
# ---------------------------------------------------------------------------
BITCOIN_BLOCK_WEIGHT_LIMIT = 4_000_000  # 4 MWU (BIP 141)
BITCOIN_BLOCK_TIME_MS = 600_000  # 10 minutes
BITCOIN_BASE_TX_OVERHEAD = 150  # version, locktime, input/output overhead
BITCOIN_WITNESS_DISCOUNT = 4  # witness bytes count as 1/4 weight

# ---------------------------------------------------------------------------
# Ethereum parameters
# ---------------------------------------------------------------------------
ETHEREUM_BLOCK_GAS_LIMIT = 30_000_000  # 30M gas (2024 baseline)
ETHEREUM_BLOCK_TIME_MS = 12_000  # 12 seconds (post-Merge)
ETHEREUM_BASE_TX_GAS = 21_000  # intrinsic gas cost per transaction
ETHEREUM_CALLDATA_GAS_PER_BYTE = 16  # non-zero calldata byte cost
ETHEREUM_BASE_TX_OVERHEAD = 120  # non-signature calldata (to, value, nonce etc.)

# Ethereum gas limit presets (2024-2026 planned increases)
# Source: Ethereum core dev discussions, EIP-4844 follow-ups
ETHEREUM_GAS_LIMITS: Dict[str, int] = {
    "2024_baseline": 30_000_000,
    "2025_current": 36_000_000,
    "2026_q1": 60_000_000,
    "2026_q2": 80_000_000,
    "2026_target": 180_000_000,
}

# ---------------------------------------------------------------------------
# Multi-signature transaction types
# ---------------------------------------------------------------------------
SOLANA_TX_TYPES: Dict[str, dict] = {
    "Simple Transfer": {"base_overhead": 200, "num_signers": 1},
    "Token Transfer": {"base_overhead": 350, "num_signers": 1},
    "Swap (DEX)": {"base_overhead": 800, "num_signers": 1},
    "Multisig 2-of-3": {"base_overhead": 300, "num_signers": 2},
}

BITCOIN_TX_TYPES: Dict[str, dict] = {
    "P2WPKH 1-in 2-out": {"base_overhead": 140, "num_signers": 1},
    "P2WPKH 2-in 2-out": {"base_overhead": 180, "num_signers": 2},
    "Multisig 2-of-3": {"base_overhead": 200, "num_signers": 2},
}

ETHEREUM_TX_TYPES: Dict[str, dict] = {
    "ETH Transfer": {"base_overhead": 0, "num_signers": 1},
    "ERC-20 Transfer": {"base_overhead": 68, "num_signers": 1},
    "Swap (DEX)": {"base_overhead": 200, "num_signers": 1},
}


@dataclass
class BlockAnalysis:
    """Result of block-space analysis for one signature scheme."""
    signature_type: str
    signature_bytes: int
    public_key_bytes: int
    tx_size_bytes: int
    txs_per_block: int
    block_utilization_pct: float
    signature_overhead_pct: float
    throughput_tps: float
    relative_to_baseline: float  # throughput ratio vs chain baseline
    # Verification time fields (populated when verification model is used)
    verification_time_ms: float = 0.0     # Time to verify all sigs in block (parallel)
    effective_tps: float = 0.0            # min(space-limited TPS, verification-limited TPS)
    bottleneck: str = "block_space"       # "block_space" or "verification"


@dataclass
class ComparativeAnalysis:
    """Side-by-side comparison of all signature schemes."""
    chain: str
    baseline: BlockAnalysis
    analyses: List[BlockAnalysis]


# ---------------------------------------------------------------------------
# Solana model
# ---------------------------------------------------------------------------

def _validate_positive(name: str, value: int | float) -> None:
    """Raise ValueError if *value* is not positive."""
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def _validate_fraction(name: str, value: float) -> None:
    """Raise ValueError if *value* is not in [0, 1]."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0, got {value}")


def analyze_solana_block_space(
    signature_type: str,
    block_size: int = SOLANA_BLOCK_SIZE_BYTES,
    base_tx_overhead: int = SOLANA_BASE_TX_OVERHEAD,
    slot_time_ms: int = SOLANA_SLOT_TIME_MS,
    num_signers: int = 1,
    vote_tx_pct: float = SOLANA_VOTE_TX_PCT_DEFAULT,
) -> BlockAnalysis:
    """Calculate how many transactions fit in a Solana block.

    Args:
        vote_tx_pct: Fraction of block space consumed by validator vote
            transactions. Default 0.0 for backwards compatibility.
            Use 0.70 for realistic estimates (70% vote transactions).
    """
    if signature_type not in SIGNATURE_SIZES:
        raise ValueError(
            f"Unknown signature type: {signature_type}. "
            f"Valid types: {list(SIGNATURE_SIZES.keys())}"
        )
    _validate_positive("block_size", block_size)
    _validate_positive("slot_time_ms", slot_time_ms)
    _validate_positive("num_signers", num_signers)
    _validate_fraction("vote_tx_pct", vote_tx_pct)

    # Calculate available block space after vote transaction overhead
    available_block_space = int(block_size * (1.0 - vote_tx_pct))

    sig_size = SIGNATURE_SIZES[signature_type] * num_signers
    pk_size = PUBLIC_KEY_SIZES[signature_type] * num_signers
    tx_size = base_tx_overhead + sig_size
    txs_per_block = available_block_space // tx_size
    tps = txs_per_block / (slot_time_ms / 1000)

    # Baseline: Ed25519 (with same vote overhead)
    ed_tx_size = base_tx_overhead + SIGNATURE_SIZES["Ed25519"] * num_signers
    ed_txs = available_block_space // ed_tx_size

    return BlockAnalysis(
        signature_type=signature_type,
        signature_bytes=sig_size,
        public_key_bytes=pk_size,
        tx_size_bytes=tx_size,
        txs_per_block=txs_per_block,
        block_utilization_pct=round((txs_per_block * tx_size / available_block_space) * 100, 2) if available_block_space > 0 else 0,
        signature_overhead_pct=round((sig_size / tx_size) * 100, 2),
        throughput_tps=round(tps, 1),
        relative_to_baseline=round(txs_per_block / ed_txs, 4) if ed_txs > 0 else 0,
    )


def compare_all_solana(
    block_size: int = SOLANA_BLOCK_SIZE_BYTES,
    base_tx_overhead: int = SOLANA_BASE_TX_OVERHEAD,
    slot_time_ms: int = SOLANA_SLOT_TIME_MS,
    num_signers: int = 1,
    vote_tx_pct: float = SOLANA_VOTE_TX_PCT_DEFAULT,
) -> ComparativeAnalysis:
    """Run Solana block-space analysis for every signature scheme."""
    analyses = [
        analyze_solana_block_space(sig, block_size, base_tx_overhead, slot_time_ms, num_signers, vote_tx_pct)
        for sig in SOLANA_SIG_TYPES
    ]
    baseline = next(a for a in analyses if a.signature_type == "Ed25519")
    return ComparativeAnalysis(chain="Solana", baseline=baseline, analyses=analyses)


# ---------------------------------------------------------------------------
# Bitcoin model
# ---------------------------------------------------------------------------

def analyze_bitcoin_block_space(
    signature_type: str,
    block_weight: int = BITCOIN_BLOCK_WEIGHT_LIMIT,
    base_tx_overhead: int = BITCOIN_BASE_TX_OVERHEAD,
    block_time_ms: int = BITCOIN_BLOCK_TIME_MS,
    witness_discount: int = BITCOIN_WITNESS_DISCOUNT,
    num_signers: int = 1,
) -> BlockAnalysis:
    """Calculate how many transactions fit in a Bitcoin block.

    Bitcoin SegWit (BIP 141) counts witness data (signatures, pubkeys)
    at 1x weight, while non-witness data counts at 4x weight.
    Total tx weight = (base_overhead * 4) + sig_bytes + pubkey_bytes.
    Block weight limit is 4,000,000 weight units (4 MWU).
    """
    if signature_type not in SIGNATURE_SIZES:
        raise ValueError(
            f"Unknown signature type: {signature_type}. "
            f"Valid types: {list(SIGNATURE_SIZES.keys())}"
        )
    _validate_positive("block_weight", block_weight)
    _validate_positive("block_time_ms", block_time_ms)
    _validate_positive("witness_discount", witness_discount)
    _validate_positive("num_signers", num_signers)

    sig_size = SIGNATURE_SIZES[signature_type] * num_signers
    pk_size = PUBLIC_KEY_SIZES[signature_type] * num_signers

    # Non-witness data at 4x weight, witness data at 1x weight
    tx_weight = (base_tx_overhead * witness_discount) + sig_size + pk_size
    txs_per_block = block_weight // tx_weight
    tps = txs_per_block / (block_time_ms / 1000)

    # Virtual size for display (weight / 4)
    tx_vsize = tx_weight / witness_discount

    # Baseline: ECDSA
    ecdsa_sig = SIGNATURE_SIZES["ECDSA"] * num_signers
    ecdsa_pk = PUBLIC_KEY_SIZES["ECDSA"] * num_signers
    ecdsa_weight = (base_tx_overhead * witness_discount) + ecdsa_sig + ecdsa_pk
    ecdsa_txs = block_weight // ecdsa_weight

    # Witness data as fraction of total weight
    witness_weight = sig_size + pk_size
    sig_overhead = round((witness_weight / tx_weight) * 100, 2)

    return BlockAnalysis(
        signature_type=signature_type,
        signature_bytes=sig_size,
        public_key_bytes=pk_size,
        tx_size_bytes=round(tx_vsize),  # virtual size for display
        txs_per_block=txs_per_block,
        block_utilization_pct=round((txs_per_block * tx_weight / block_weight) * 100, 2),
        signature_overhead_pct=sig_overhead,
        throughput_tps=round(tps, 2),
        relative_to_baseline=round(txs_per_block / ecdsa_txs, 4) if ecdsa_txs > 0 else 0,
    )


def compare_all_bitcoin(
    block_weight: int = BITCOIN_BLOCK_WEIGHT_LIMIT,
    base_tx_overhead: int = BITCOIN_BASE_TX_OVERHEAD,
    block_time_ms: int = BITCOIN_BLOCK_TIME_MS,
    witness_discount: int = BITCOIN_WITNESS_DISCOUNT,
    num_signers: int = 1,
) -> ComparativeAnalysis:
    """Run Bitcoin block-space analysis for every signature scheme."""
    analyses = [
        analyze_bitcoin_block_space(sig, block_weight, base_tx_overhead, block_time_ms, witness_discount, num_signers)
        for sig in BITCOIN_SIG_TYPES
    ]
    baseline = next(a for a in analyses if a.signature_type == "ECDSA")
    return ComparativeAnalysis(chain="Bitcoin", baseline=baseline, analyses=analyses)


# ---------------------------------------------------------------------------
# Ethereum model
# ---------------------------------------------------------------------------

def analyze_ethereum_block_space(
    signature_type: str,
    block_gas_limit: int = ETHEREUM_BLOCK_GAS_LIMIT,
    base_tx_overhead: int = ETHEREUM_BASE_TX_OVERHEAD,
    block_time_ms: int = ETHEREUM_BLOCK_TIME_MS,
    base_tx_gas: int = ETHEREUM_BASE_TX_GAS,
    calldata_gas_per_byte: int = ETHEREUM_CALLDATA_GAS_PER_BYTE,
    num_signers: int = 1,
    execution_gas: int = 0,
) -> BlockAnalysis:
    """Calculate how many transactions fit in an Ethereum block.

    Ethereum charges gas for calldata (signature + pubkey data):
    - 16 gas per non-zero byte (conservative: assume all non-zero)
    - 21,000 base gas per transaction
    - Additional gas for non-signature calldata (to, value, etc.)

    Args:
        execution_gas: Additional execution gas per transaction (e.g. contract
            logic, storage operations).  Default 0 models simple transfers.
            Typical values: ~65,000 for ERC-20 transfer, ~150,000+ for DEX swap.
    """
    if signature_type not in SIGNATURE_SIZES:
        raise ValueError(
            f"Unknown signature type: {signature_type}. "
            f"Valid types: {list(SIGNATURE_SIZES.keys())}"
        )
    _validate_positive("block_gas_limit", block_gas_limit)
    _validate_positive("block_time_ms", block_time_ms)
    _validate_positive("base_tx_gas", base_tx_gas)
    _validate_positive("calldata_gas_per_byte", calldata_gas_per_byte)
    _validate_positive("num_signers", num_signers)

    sig_size = SIGNATURE_SIZES[signature_type] * num_signers
    pk_size = PUBLIC_KEY_SIZES[signature_type] * num_signers

    # Gas cost per transaction
    calldata_bytes = sig_size + pk_size + base_tx_overhead
    tx_gas = base_tx_gas + (calldata_bytes * calldata_gas_per_byte) + execution_gas
    txs_per_block = block_gas_limit // tx_gas
    tps = txs_per_block / (block_time_ms / 1000)

    # Equivalent "transaction size" for display (calldata bytes)
    tx_size = base_tx_overhead + sig_size + pk_size

    # Baseline: ECDSA (with same execution gas)
    ecdsa_sig = SIGNATURE_SIZES["ECDSA"] * num_signers
    ecdsa_pk = PUBLIC_KEY_SIZES["ECDSA"] * num_signers
    ecdsa_calldata = ecdsa_sig + ecdsa_pk + base_tx_overhead
    ecdsa_gas = base_tx_gas + (ecdsa_calldata * calldata_gas_per_byte) + execution_gas
    ecdsa_txs = block_gas_limit // ecdsa_gas

    # Signature overhead
    sig_gas = (sig_size + pk_size) * calldata_gas_per_byte
    sig_overhead = round((sig_gas / tx_gas) * 100, 2)

    return BlockAnalysis(
        signature_type=signature_type,
        signature_bytes=sig_size,
        public_key_bytes=pk_size,
        tx_size_bytes=tx_size,
        txs_per_block=txs_per_block,
        block_utilization_pct=round((txs_per_block * tx_gas / block_gas_limit) * 100, 2),
        signature_overhead_pct=sig_overhead,
        throughput_tps=round(tps, 2),
        relative_to_baseline=round(txs_per_block / ecdsa_txs, 4) if ecdsa_txs > 0 else 0,
    )


def compare_all_ethereum(
    block_gas_limit: int = ETHEREUM_BLOCK_GAS_LIMIT,
    base_tx_overhead: int = ETHEREUM_BASE_TX_OVERHEAD,
    block_time_ms: int = ETHEREUM_BLOCK_TIME_MS,
    num_signers: int = 1,
) -> ComparativeAnalysis:
    """Run Ethereum block-space analysis for every signature scheme."""
    analyses = [
        analyze_ethereum_block_space(sig, block_gas_limit, base_tx_overhead, block_time_ms,
                                     num_signers=num_signers)
        for sig in ETHEREUM_SIG_TYPES
    ]
    baseline = next(a for a in analyses if a.signature_type == "ECDSA")
    return ComparativeAnalysis(chain="Ethereum", baseline=baseline, analyses=analyses)


# ---------------------------------------------------------------------------
# Verification time integration
# ---------------------------------------------------------------------------

def enrich_with_verification(
    analysis: BlockAnalysis,
    block_time_ms: float,
    num_cores: int = 4,
    use_batch: bool = True,
) -> BlockAnalysis:
    """Add verification time data to a BlockAnalysis result.

    Computes how long it takes to verify all signatures in the block
    and determines whether verification or block space is the bottleneck.
    """
    from blockchain.verification import (
        compute_block_verification_time,
        VERIFICATION_PROFILES,
    )

    if analysis.signature_type not in VERIFICATION_PROFILES:
        return analysis

    vr = compute_block_verification_time(
        algorithm=analysis.signature_type,
        txs_per_block=analysis.txs_per_block,
        block_time_ms=block_time_ms,
        num_cores=num_cores,
        use_batch=use_batch,
    )

    space_tps = analysis.throughput_tps
    verify_tps = vr.effective_tps

    analysis.verification_time_ms = vr.parallel_time_ms
    analysis.effective_tps = round(min(space_tps, verify_tps), 2)
    analysis.bottleneck = "verification" if verify_tps < space_tps else "block_space"

    return analysis


if __name__ == "__main__":
    for chain_name, compare_fn in [("SOLANA", compare_all_solana),
                                    ("BITCOIN", compare_all_bitcoin),
                                    ("ETHEREUM", compare_all_ethereum)]:
        comp = compare_fn()
        baseline_name = comp.baseline.signature_type
        print(f"\n{'=' * 90}")
        print(f"  {chain_name} (baseline: {baseline_name})")
        print(f"{'=' * 90}")
        print(f"{'Scheme':<35} {'Sig(B)':>7} {'Tx(B)':>7} {'Txs/blk':>9} {'TPS':>10} {'vs baseline':>11}")
        print("-" * 85)
        for a in comp.analyses:
            print(
                f"{a.signature_type:<35} {a.signature_bytes:>7} {a.tx_size_bytes:>7} "
                f"{a.txs_per_block:>9} {a.throughput_tps:>10.2f} {a.relative_to_baseline:>10.2%}"
            )
