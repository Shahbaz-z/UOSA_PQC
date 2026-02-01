"""Solana block-space model for PQC signature impact analysis.

Models the effect of replacing Ed25519 with post-quantum signature
schemes on Solana transaction throughput.

Assumptions and limitations (document in report):
- We model *signature contribution* to transaction size, not full
  transaction serialization.
- Base transaction overhead (accounts, instructions, blockhash) is
  approximated as a constant.
- Solana practical block size is ~6 MB (theoretical 32 MB, but
  leader schedule and vote overhead reduce usable space).

Sources:
- Solana docs: https://docs.solana.com/developing/programming-model/transactions
- NIST PQC standards for signature sizes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# ---------------------------------------------------------------------------
# Solana parameters
# ---------------------------------------------------------------------------
SOLANA_BLOCK_SIZE_BYTES = 6_000_000  # ~6 MB practical limit
SOLANA_SLOT_TIME_MS = 400  # target slot time

# Base transaction overhead *excluding* signature(s):
# 1 signature slot (will be replaced) + 1 blockhash (32) + compact-u16
# for account count + 2 account addresses (32 each) + instruction data (~100).
# Total non-signature overhead ~ 230-270 bytes; we use 250 as a midpoint.
SOLANA_BASE_TX_OVERHEAD = 250

# ---------------------------------------------------------------------------
# Signature sizes (bytes)
# ---------------------------------------------------------------------------
SIGNATURE_SIZES: Dict[str, int] = {
    "Ed25519": 64,
    "Dilithium2": 2_420,
    "Dilithium3": 3_293,
    "Dilithium5": 4_595,
    "Hybrid-Ed25519+Dilithium2": 64 + 2_420,
    "Hybrid-Ed25519+Dilithium3": 64 + 3_293,
    "Hybrid-Ed25519+Dilithium5": 64 + 4_595,
}

# Public-key sizes for full-transaction modeling
PUBLIC_KEY_SIZES: Dict[str, int] = {
    "Ed25519": 32,
    "Dilithium2": 1_312,
    "Dilithium3": 1_952,
    "Dilithium5": 2_592,
    "Hybrid-Ed25519+Dilithium2": 32 + 1_312,
    "Hybrid-Ed25519+Dilithium3": 32 + 1_952,
    "Hybrid-Ed25519+Dilithium5": 32 + 2_592,
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
    throughput_tps: float  # txs per second based on slot time
    relative_to_ed25519: float  # throughput ratio vs Ed25519


@dataclass
class ComparativeAnalysis:
    """Side-by-side comparison of all signature schemes."""
    baseline: BlockAnalysis
    analyses: List[BlockAnalysis]


def analyze_block_space(
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

    # Compute relative throughput vs Ed25519
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
        relative_to_ed25519=round(txs_per_block / ed_txs, 4) if ed_txs > 0 else 0,
    )


def compare_all(
    block_size: int = SOLANA_BLOCK_SIZE_BYTES,
    base_tx_overhead: int = SOLANA_BASE_TX_OVERHEAD,
    slot_time_ms: int = SOLANA_SLOT_TIME_MS,
) -> ComparativeAnalysis:
    """Run block-space analysis for every signature scheme."""
    analyses = [
        analyze_block_space(sig, block_size, base_tx_overhead, slot_time_ms)
        for sig in SIGNATURE_SIZES
    ]
    baseline = next(a for a in analyses if a.signature_type == "Ed25519")
    return ComparativeAnalysis(baseline=baseline, analyses=analyses)


if __name__ == "__main__":
    comp = compare_all()
    print(f"{'Scheme':<35} {'Sig(B)':>7} {'Tx(B)':>7} {'Txs/blk':>9} {'TPS':>10} {'vs Ed25519':>11}")
    print("-" * 85)
    for a in comp.analyses:
        print(
            f"{a.signature_type:<35} {a.signature_bytes:>7} {a.tx_size_bytes:>7} "
            f"{a.txs_per_block:>9} {a.throughput_tps:>10.1f} {a.relative_to_ed25519:>10.2%}"
        )
