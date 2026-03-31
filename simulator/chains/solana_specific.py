"""Solana-specific transaction model: vote transaction overhead and compute budget.

Models Solana's two-tier transaction system:
  1. Vote transactions — emitted every slot by validators attesting to the chain.
     These consume 70-80% of block space in practice.
  2. User transactions — normal transfers, DeFi, NFT mints, etc.

Under PQC migration, vote transaction sizes explode because each validator
must attest with a larger signature. This creates a hard ceiling well before
user transactions even compete: if vote txs alone saturate the block, the
chain halts regardless of user demand.

Gulf Stream integration:
  Solana forwards pending transactions to the next 4 expected leaders.
  With PQC signatures, each forwarded transaction is larger → more bandwidth
  consumed in prefetch, degrading network performance before blocks are even
  proposed.

References:
    - Solana docs: https://docs.solana.com/developing/programming-model/transactions
    - Solana validator vote transaction spec: https://docs.solana.com/consensus/fork-generation
    - Compute budget: https://docs.solana.com/developing/programming-model/runtime
    - liboqs benchmarks: https://openquantumsafe.org/benchmarking/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fraction of block space consumed by vote transactions on mainnet.
# Source: Solana Beach block explorer, 2024-2025 average
VOTE_TX_FRACTION: float = 0.75

# Base size of a vote transaction body (excluding signature)
# Covers: slot, bank hash, hash(slot), lockouts, timestamp, reward
VOTE_TX_BASE_BYTES: int = 130

# Ed25519 vote transaction total size (Ed25519 sig = 64 bytes, pk = 32 bytes)
VOTE_TX_ED25519_SIZE: int = 214  # 130 + 64 (sig) + 32 (pk) - overlap/varint ≈ 214

# Solana block size limits
BLOCK_SIZE_BYTES: int = 6_291_456       # 6 MB practical limit (not 32 MB theoretical)
BLOCK_COMPUTE_UNIT_LIMIT: int = 48_000_000  # 48M CUs per block (mainnet cap)

# Gulf Stream: forward txs to next N leaders
GULF_STREAM_LEADERS: int = 4

# Compute unit costs per signature verification (estimated from cycle benchmarks)
# Solana's runtime charges CUs for signature verification as part of tx processing.
# Ed25519 program: https://docs.solana.com/developing/runtime-facilities/programs#ed25519-program
CU_COSTS: Dict[str, int] = {
    "Ed25519":      100,      # Solana native Ed25519 program cost
    "ECDSA":        200,      # secp256k1 program (slightly heavier)
    "ML-DSA-44":    5_000,    # estimated from ~83k cycles × (CU/cycle ratio)
    "ML-DSA-65":    8_000,    # estimated
    "ML-DSA-87":    12_000,   # estimated
    "Falcon-512":   2_500,    # fast verify — ~42k cycles
    "Falcon-1024":  4_500,    # ~75k cycles
    "SLH-DSA-128s": 40_000,   # very slow: ~667k cycles
    "SLH-DSA-128f":  3_500,   # fast variant: ~58k cycles
    "SLH-DSA-192s": 65_000,
    "SLH-DSA-192f":  5_500,
    "SLH-DSA-256s": 95_000,
    "SLH-DSA-256f":  8_000,
    # Hybrid schemes
    "Hybrid-Ed25519+ML-DSA-44":   5_100,
    "Hybrid-Ed25519+ML-DSA-65":   8_100,
    "Hybrid-Ed25519+ML-DSA-87":  12_100,
    "Hybrid-Ed25519+Falcon-512":  2_600,
    "Hybrid-Ed25519+Falcon-1024": 4_600,
}


# ---------------------------------------------------------------------------
# Transaction size model
# ---------------------------------------------------------------------------

@dataclass
class SolanaTxModel:
    """Models Solana transaction sizes and block capacity under PQC.

    Attributes:
        validators_per_slot: Number of validators attesting per slot (mainnet: ~1500,
            but for block-size analysis we care about how many UNIQUE vote txs
            are included in a block — typically 1 per validator per slot).
        vote_tx_fraction: Fraction of block bytes consumed by vote transactions.
        block_size_bytes: Practical block size limit in bytes.
        compute_unit_limit: Per-block compute unit ceiling.
    """

    validators_per_slot: int   = 1_500
    vote_tx_fraction: float    = VOTE_TX_FRACTION
    block_size_bytes: int      = BLOCK_SIZE_BYTES
    compute_unit_limit: int    = BLOCK_COMPUTE_UNIT_LIMIT

    def vote_tx_size(self, sig_algorithm: str) -> int:
        """Size of a single vote transaction in bytes.

        A vote transaction contains:
          - Fixed-size vote body (slot, hash, lockouts, timestamp)
          - Signature (algorithm-dependent)
          - Public key (algorithm-dependent)

        Args:
            sig_algorithm: Signature scheme name.

        Returns:
            Vote transaction size in bytes.
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
        sig_size = SIGNATURE_SIZES.get(sig_algorithm, 64)
        pk_size  = PUBLIC_KEY_SIZES.get(sig_algorithm, 32)
        return VOTE_TX_BASE_BYTES + sig_size + pk_size

    def user_tx_size(
        self,
        sig_algorithm: str,
        calldata_bytes: int = 100,
    ) -> int:
        """Size of a user transaction in bytes.

        Args:
            sig_algorithm:  Signature scheme name.
            calldata_bytes: Instruction data / calldata bytes (default 100).

        Returns:
            User transaction size in bytes.
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        # Solana transaction structure:
        #   header (3 bytes) + accounts (n × 32 bytes) + blockhash (32 bytes)
        #   + instructions + signature(s)
        HEADER_BYTES    = 3
        ACCOUNT_BYTES   = 32 * 3  # typical: fee payer + 2 accounts
        BLOCKHASH_BYTES = 32
        INSTRUCTION_OVERHEAD = 4   # program id index + account indices + data length

        sig_size = SIGNATURE_SIZES.get(sig_algorithm, 64)
        pk_size  = PUBLIC_KEY_SIZES.get(sig_algorithm, 32)

        return (
            HEADER_BYTES
            + ACCOUNT_BYTES
            + BLOCKHASH_BYTES
            + INSTRUCTION_OVERHEAD
            + sig_size
            + pk_size
            + calldata_bytes
        )

    def block_capacity_analysis(
        self,
        sig_algorithm: str,
        block_size_bytes: Optional[int] = None,
    ) -> Dict:
        """Analyse block capacity under a given signature algorithm.

        Computes the split between vote and user transaction space, and
        flags whether vote transactions alone would saturate the block.

        Args:
            sig_algorithm:   Signature scheme name.
            block_size_bytes: Override block size (defaults to self.block_size_bytes).

        Returns:
            Dict with keys:
                vote_tx_size_bytes:     Size of one vote tx.
                vote_tx_count:          Expected vote txs per block.
                vote_tx_bytes_total:    Total bytes consumed by all vote txs.
                user_tx_capacity_bytes: Remaining bytes for user txs.
                max_user_txs:           Max user txs at default (100B calldata) size.
                vote_overhead_ratio:    Fraction of block used by votes.
                is_vote_saturated:      True if votes alone exceed block size.
                compute_unit_total_votes: CUs consumed by vote txs alone.
                is_cu_saturated:        True if vote CUs exceed block CU limit.
        """
        limit = block_size_bytes or self.block_size_bytes

        vtx_size   = self.vote_tx_size(sig_algorithm)
        vote_total = vtx_size * self.validators_per_slot

        user_capacity = max(0, limit - vote_total)
        user_tx_size  = self.user_tx_size(sig_algorithm)
        max_user_txs  = user_capacity // user_tx_size if user_tx_size > 0 else 0

        vote_ratio = vote_total / limit if limit > 0 else 1.0

        # Compute units
        cu_per_vote  = CU_COSTS.get(sig_algorithm, 8_000)
        vote_cu_total = cu_per_vote * self.validators_per_slot

        return {
            "sig_algorithm":            sig_algorithm,
            "vote_tx_size_bytes":       vtx_size,
            "vote_tx_count":            self.validators_per_slot,
            "vote_tx_bytes_total":      vote_total,
            "user_tx_capacity_bytes":   user_capacity,
            "max_user_txs":             max_user_txs,
            "vote_overhead_ratio":      vote_ratio,
            "is_vote_saturated":        vote_total >= limit,
            "compute_unit_total_votes": vote_cu_total,
            "is_cu_saturated":          vote_cu_total >= self.compute_unit_limit,
            "block_size_bytes":         limit,
        }

    def compute_unit_cost(self, sig_algorithm: str) -> int:
        """Compute units consumed per signature verification.

        Args:
            sig_algorithm: Signature scheme name.

        Returns:
            Compute units consumed.
        """
        return CU_COSTS.get(sig_algorithm, 8_000)

    def gulf_stream_prefetch_overhead(
        self,
        sig_algorithm: str,
        pending_txs: int = 1_000,
        leaders_ahead: int = GULF_STREAM_LEADERS,
    ) -> Dict:
        """Bandwidth overhead from Gulf Stream prefetch under PQC.

        Gulf Stream forwards pending transactions to the next `leaders_ahead`
        expected leaders. Each forwarded transaction is now larger under PQC,
        increasing network load before blocks are even proposed.

        Args:
            sig_algorithm: Signature scheme name.
            pending_txs:   Number of pending user transactions forwarded.
            leaders_ahead: Number of upcoming leaders to forward to.

        Returns:
            Dict with prefetch_bytes_total, bandwidth_vs_ed25519_ratio.
        """
        pqc_user_size = self.user_tx_size(sig_algorithm)
        ed_user_size  = self.user_tx_size("Ed25519")

        total_forwarded_bytes = pqc_user_size * pending_txs * leaders_ahead
        baseline_bytes        = ed_user_size  * pending_txs * leaders_ahead

        return {
            "sig_algorithm":               sig_algorithm,
            "pqc_user_tx_size_bytes":      pqc_user_size,
            "ed25519_user_tx_size_bytes":  ed_user_size,
            "total_forwarded_bytes":       total_forwarded_bytes,
            "baseline_forwarded_bytes":    baseline_bytes,
            "bandwidth_vs_ed25519_ratio":  (
                total_forwarded_bytes / baseline_bytes if baseline_bytes > 0 else float("inf")
            ),
            "leaders_ahead":               leaders_ahead,
            "pending_txs":                 pending_txs,
        }

    def migration_capacity_curve(
        self,
        pqc_algo: str,
        pqc_fractions: Optional[list] = None,
    ) -> list:
        """Block capacity as a function of PQC adoption fraction.

        Models the transition from 100% classical to 100% PQC for vote
        and user transactions.

        Args:
            pqc_algo:       Target PQC algorithm.
            pqc_fractions:  List of adoption fractions [0..1].

        Returns:
            List of dicts, one per fraction point.
        """
        if pqc_fractions is None:
            pqc_fractions = [i / 20 for i in range(21)]  # 0%, 5%, ..., 100%

        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

        results = []
        for frac in pqc_fractions:
            # Weighted average vote tx size
            pqc_vote  = self.vote_tx_size(pqc_algo)
            ed_vote   = self.vote_tx_size("Ed25519")
            avg_vote  = frac * pqc_vote + (1 - frac) * ed_vote

            # Weighted average user tx size
            pqc_user  = self.user_tx_size(pqc_algo)
            ed_user   = self.user_tx_size("Ed25519")
            avg_user  = frac * pqc_user + (1 - frac) * ed_user

            vote_total    = avg_vote * self.validators_per_slot
            user_capacity = max(0, self.block_size_bytes - vote_total)
            max_user_txs  = int(user_capacity / avg_user) if avg_user > 0 else 0

            # CU analysis
            pqc_cu   = CU_COSTS.get(pqc_algo, 8_000)
            ed_cu    = CU_COSTS.get("Ed25519", 100)
            avg_cu   = frac * pqc_cu + (1 - frac) * ed_cu
            vote_cus = avg_cu * self.validators_per_slot

            results.append({
                "pqc_fraction":             frac,
                "avg_vote_tx_size_bytes":   avg_vote,
                "avg_user_tx_size_bytes":   avg_user,
                "vote_bytes_total":         vote_total,
                "user_tx_capacity_bytes":   user_capacity,
                "max_user_txs":             max_user_txs,
                "vote_overhead_ratio":      vote_total / self.block_size_bytes,
                "is_vote_saturated":        vote_total >= self.block_size_bytes,
                "vote_cu_total":            vote_cus,
                "is_cu_saturated":          vote_cus >= self.compute_unit_limit,
            })

        return results


# ---------------------------------------------------------------------------
# Module-level defaults
# ---------------------------------------------------------------------------

DEFAULT_SOLANA_TX_MODEL = SolanaTxModel()
