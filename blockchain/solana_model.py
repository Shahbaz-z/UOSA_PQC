"""Blockchain block-space model for PQC signature impact analysis.

Models the effect of replacing classical signatures with post-quantum
schemes on transaction throughput for Solana and Bitcoin.

Assumptions and limitations (document in report):
- We model *signature contribution* to transaction size, not full
  transaction serialization.
- Base transaction overhead is approximated as a constant.
- Solana practical block size is ~6 MB (theoretical 32 MB).
- Bitcoin block weight limit is 4 MWU; SegWit witness discount applies.

Sources:
- Solana docs: https://docs.solana.com/developing/programming-model/transactions
- Bitcoin BIP 141 (SegWit): witness data counted at 1/4 weight
- NIST PQC standards for signature sizes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# ---------------------------------------------------------------------------
# Signature & public-key sizes (bytes) – shared across chain models
# ---------------------------------------------------------------------------
SIGNATURE_SIZES: Dict[str, int] = {
    "Ed25519": 64,
    "ECDSA": 72,  # DER-encoded secp256k1 (Bitcoin baseline)
    "Dilithium2": 2_420,
    "Dilithium3": 3_293,
    "Dilithium5": 4_595,
    "ML-DSA-44": 2_420,
    "ML-DSA-65": 3_293,
    "ML-DSA-87": 4_595,
    "Falcon-512": 666,
    "Falcon-1024": 1_280,
    "Hybrid-Ed25519+Dilithium2": 64 + 2_420,
    "Hybrid-Ed25519+Dilithium3": 64 + 3_293,
    "Hybrid-Ed25519+Dilithium5": 64 + 4_595,
    "Hybrid-Ed25519+Falcon-512": 64 + 666,
    "Hybrid-Ed25519+Falcon-1024": 64 + 1_280,
}

PUBLIC_KEY_SIZES: Dict[str, int] = {
    "Ed25519": 32,
    "ECDSA": 33,  # compressed secp256k1
    "Dilithium2": 1_312,
    "Dilithium3": 1_952,
    "Dilithium5": 2_592,
    "ML-DSA-44": 1_312,
    "ML-DSA-65": 1_952,
    "ML-DSA-87": 2_592,
    "Falcon-512": 897,
    "Falcon-1024": 1_793,
    "Hybrid-Ed25519+Dilithium2": 32 + 1_312,
    "Hybrid-Ed25519+Dilithium3": 32 + 1_952,
    "Hybrid-Ed25519+Dilithium5": 32 + 2_592,
    "Hybrid-Ed25519+Falcon-512": 32 + 897,
    "Hybrid-Ed25519+Falcon-1024": 32 + 1_793,
}

# Subsets for each chain (Solana uses Ed25519 baseline, Bitcoin uses ECDSA)
SOLANA_SIG_TYPES = [k for k in SIGNATURE_SIZES if k != "ECDSA"]
BITCOIN_SIG_TYPES = [k for k in SIGNATURE_SIZES if k != "Ed25519"]

# ---------------------------------------------------------------------------
# Solana parameters
# ---------------------------------------------------------------------------
SOLANA_BLOCK_SIZE_BYTES = 6_000_000  # ~6 MB practical limit
SOLANA_SLOT_TIME_MS = 400  # target slot time
SOLANA_BASE_TX_OVERHEAD = 250  # accounts, instructions, blockhash

# ---------------------------------------------------------------------------
# Bitcoin parameters
# ---------------------------------------------------------------------------
BITCOIN_BLOCK_WEIGHT_LIMIT = 4_000_000  # 4 MWU (BIP 141)
BITCOIN_BLOCK_TIME_MS = 600_000  # 10 minutes
BITCOIN_BASE_TX_OVERHEAD = 150  # version, locktime, input/output overhead
BITCOIN_WITNESS_DISCOUNT = 4  # witness bytes count as 1/4 weight


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


@dataclass
class ComparativeAnalysis:
    """Side-by-side comparison of all signature schemes."""
    chain: str
    baseline: BlockAnalysis
    analyses: List[BlockAnalysis]


# ---------------------------------------------------------------------------
# Solana model
# ---------------------------------------------------------------------------

def analyze_solana_block_space(
    signature_type: str,
    block_size: int = SOLANA_BLOCK_SIZE_BYTES,
    base_tx_overhead: int = SOLANA_BASE_TX_OVERHEAD,
    slot_time_ms: int = SOLANA_SLOT_TIME_MS,
) -> BlockAnalysis:
    """Calculate how many transactions fit in a Solana block."""
    sig_size = SIGNATURE_SIZES[signature_type]
    pk_size = PUBLIC_KEY_SIZES[signature_type]
    tx_size = base_tx_overhead + sig_size
    txs_per_block = block_size // tx_size
    tps = txs_per_block / (slot_time_ms / 1000)

    # Baseline: Ed25519
    ed_tx_size = base_tx_overhead + SIGNATURE_SIZES["Ed25519"]
    ed_txs = block_size // ed_tx_size

    return BlockAnalysis(
        signature_type=signature_type,
        signature_bytes=sig_size,
        public_key_bytes=pk_size,
        tx_size_bytes=tx_size,
        txs_per_block=txs_per_block,
        block_utilization_pct=round((txs_per_block * tx_size / block_size) * 100, 2),
        signature_overhead_pct=round((sig_size / tx_size) * 100, 2),
        throughput_tps=round(tps, 1),
        relative_to_baseline=round(txs_per_block / ed_txs, 4) if ed_txs > 0 else 0,
    )


def compare_all_solana(
    block_size: int = SOLANA_BLOCK_SIZE_BYTES,
    base_tx_overhead: int = SOLANA_BASE_TX_OVERHEAD,
    slot_time_ms: int = SOLANA_SLOT_TIME_MS,
) -> ComparativeAnalysis:
    """Run Solana block-space analysis for every signature scheme."""
    analyses = [
        analyze_solana_block_space(sig, block_size, base_tx_overhead, slot_time_ms)
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
) -> BlockAnalysis:
    """Calculate how many transactions fit in a Bitcoin block.

    Bitcoin SegWit (BIP 141) counts witness data (signatures, pubkeys)
    at 1x weight, while non-witness data counts at 4x weight.
    Total tx weight = (base_overhead * 4) + sig_bytes + pubkey_bytes.
    Block weight limit is 4,000,000 weight units (4 MWU).
    """
    sig_size = SIGNATURE_SIZES[signature_type]
    pk_size = PUBLIC_KEY_SIZES[signature_type]

    # Non-witness data at 4x weight, witness data at 1x weight
    tx_weight = (base_tx_overhead * witness_discount) + sig_size + pk_size
    txs_per_block = block_weight // tx_weight
    tps = txs_per_block / (block_time_ms / 1000)

    # Virtual size for display (weight / 4)
    tx_vsize = tx_weight / witness_discount

    # Baseline: ECDSA
    ecdsa_sig = SIGNATURE_SIZES["ECDSA"]
    ecdsa_pk = PUBLIC_KEY_SIZES["ECDSA"]
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
) -> ComparativeAnalysis:
    """Run Bitcoin block-space analysis for every signature scheme."""
    analyses = [
        analyze_bitcoin_block_space(sig, block_weight, base_tx_overhead, block_time_ms, witness_discount)
        for sig in BITCOIN_SIG_TYPES
    ]
    baseline = next(a for a in analyses if a.signature_type == "ECDSA")
    return ComparativeAnalysis(chain="Bitcoin", baseline=baseline, analyses=analyses)


# ---------------------------------------------------------------------------
# Backwards-compatible aliases (used by existing tests and Streamlit app)
# ---------------------------------------------------------------------------
def analyze_block_space(signature_type, block_size=SOLANA_BLOCK_SIZE_BYTES,
                        base_tx_overhead=SOLANA_BASE_TX_OVERHEAD,
                        slot_time_ms=SOLANA_SLOT_TIME_MS):
    return analyze_solana_block_space(signature_type, block_size, base_tx_overhead, slot_time_ms)


def compare_all(block_size=SOLANA_BLOCK_SIZE_BYTES,
                base_tx_overhead=SOLANA_BASE_TX_OVERHEAD,
                slot_time_ms=SOLANA_SLOT_TIME_MS):
    return compare_all_solana(block_size, base_tx_overhead, slot_time_ms)


if __name__ == "__main__":
    for chain_name, compare_fn in [("SOLANA", compare_all_solana), ("BITCOIN", compare_all_bitcoin)]:
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
