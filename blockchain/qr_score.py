"""Quantum Resistance (QR) scoring model for blockchain signature schemes.

Produces a composite quantum-resistance readiness score for each blockchain
based on multiple dimensions:

1. **Signature Security** -- Is the signature scheme quantum-resistant?
2. **Throughput Retention** -- How much capacity is preserved after PQC migration?
3. **Migration Feasibility** -- How practical is the migration path?
4. **Key/Signature Size** -- How much do artifact sizes increase?
5. **ZK-STARK Readiness** -- Can the chain leverage quantum-resistant ZK proofs?

Each dimension is scored 0-100 and weighted to produce a composite score.

Limitations:
- Scores reflect *static analysis* of protocol parameters, not real-world
  deployment complexity (governance, ecosystem readiness, etc.)
- Migration feasibility is a qualitative assessment encoded as numeric scores
- ZK-STARK readiness is Ethereum-centric (other chains have different L2 models)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from blockchain.solana_model import (
    compare_all_solana, compare_all_bitcoin, compare_all_ethereum,
    SIGNATURE_SIZES, PUBLIC_KEY_SIZES,
    SOLANA_VOTE_TX_PCT_REALISTIC,
)

# Classical (non-PQC) signature schemes -- excluded from PQC scoring
CLASSICAL_SIGS = {"Ed25519", "ECDSA", "Schnorr"}

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "throughput_retention": 0.30,
    "signature_size": 0.20,
    "migration_feasibility": 0.25,
    "zk_readiness": 0.15,
    "algorithm_diversity": 0.10,
}

# ---------------------------------------------------------------------------
# Migration feasibility scores (qualitative -> numeric)
# ---------------------------------------------------------------------------
MIGRATION_FEASIBILITY: Dict[str, Dict[str, float]] = {
    "Solana": {
        "score": 55.0,
        "hard_fork_required": True,
        "account_model": "account",
        "rationale": (
            "Solana uses an account model (easier migration than UTXO), but "
            "the 400ms slot time makes verification-heavy PQC schemes challenging. "
            "Vote transactions (70-80% of blocks) also need signature upgrades. "
            "No active PQC migration proposal yet."
        ),
    },
    "Bitcoin": {
        "score": 40.0,
        "hard_fork_required": True,
        "account_model": "UTXO",
        "rationale": (
            "Bitcoin's UTXO model requires all unspent outputs to be migrated. "
            "Addresses with exposed public keys (reused P2PKH) are highest risk. "
            "Requires hard fork or new SegWit version. Conservative governance "
            "makes rapid PQC adoption unlikely. BIP process is slow by design."
        ),
    },
    "Ethereum": {
        "score": 70.0,
        "hard_fork_required": False,  # Account abstraction enables gradual migration
        "account_model": "account",
        "rationale": (
            "Ethereum's account abstraction (EIP-4337) enables smart contract "
            "wallets to adopt PQC signatures without a hard fork. Gas limit "
            "increases (30M->180M) accommodate larger PQC artifacts. However, "
            "EOA migration still requires protocol changes. Active research "
            "community with multiple PQC proposals."
        ),
    },
}

# ---------------------------------------------------------------------------
# ZK-STARK readiness scores
# ---------------------------------------------------------------------------
ZK_READINESS: Dict[str, Dict[str, float]] = {
    "Solana": {
        "score": 30.0,
        "rationale": (
            "Solana has limited ZK proof infrastructure compared to Ethereum. "
            "No native ZK verifier precompiles. Some projects (Light Protocol) "
            "explore ZK on Solana but it's not a core scaling strategy."
        ),
    },
    "Bitcoin": {
        "score": 15.0,
        "rationale": (
            "Bitcoin Script is intentionally limited and does not support "
            "ZK proof verification natively. BitVM and other proposals are "
            "experimental. ZK-STARKs are not viable on Bitcoin L1."
        ),
    },
    "Ethereum": {
        "score": 85.0,
        "rationale": (
            "Ethereum has native bn128 precompiles (EIP-196/197) for SNARK "
            "verification. Multiple ZK rollups (StarkNet, zkSync, Polygon zkEVM) "
            "are live. STARK verification is expensive but feasible with gas "
            "limit increases. EIP-4844 blobs reduce ZK proof data costs."
        ),
    },
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    """Score for a single dimension of quantum resistance."""
    dimension: str
    score: float          # 0-100
    weight: float         # 0-1
    weighted_score: float # score * weight
    detail: str           # Human-readable explanation


@dataclass
class ChainQRScore:
    """Complete quantum resistance assessment for a blockchain."""
    chain: str
    composite_score: float  # 0-100 weighted composite
    grade: str              # A-F letter grade
    dimensions: List[DimensionScore]
    best_pqc_algorithm: str
    best_pqc_retention: float
    recommendation: str


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _throughput_retention_score(chain: str) -> DimensionScore:
    """Score based on best PQC algorithm's throughput retention.

    100 = no throughput loss, 0 = total loss.
    Uses Falcon-512 as the best PQC option for all chains.
    """
    if chain == "Solana":
        comp = compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC)
    elif chain == "Bitcoin":
        comp = compare_all_bitcoin()
    else:
        comp = compare_all_ethereum()

    # Best PQC option (excluding all classical signatures)
    pqc_analyses = [a for a in comp.analyses if a.signature_type not in CLASSICAL_SIGS]
    best = max(pqc_analyses, key=lambda a: a.relative_to_baseline)
    score = best.relative_to_baseline * 100  # 0-100 scale

    return DimensionScore(
        dimension="throughput_retention",
        score=round(score, 1),
        weight=SCORE_WEIGHTS["throughput_retention"],
        weighted_score=round(score * SCORE_WEIGHTS["throughput_retention"], 2),
        detail=f"Best PQC ({best.signature_type}) retains {best.relative_to_baseline:.1%} of baseline throughput",
    )


def _signature_size_score(chain: str) -> DimensionScore:
    """Score based on signature size increase from classical to best PQC.

    Smaller PQC signatures score higher. Uses log scale since sizes vary 10x-700x.
    Score = max(0, 100 - 15 * log2(pqc_size / classical_size))
    """
    import math

    if chain == "Solana":
        classical_size = SIGNATURE_SIZES["Ed25519"]  # 64 B
    else:
        classical_size = SIGNATURE_SIZES["ECDSA"]  # 72 B

    # Best PQC = Falcon-512 (smallest PQC sig)
    pqc_size = SIGNATURE_SIZES["Falcon-512"]  # 666 B
    ratio = pqc_size / classical_size
    score = max(0, 100 - 15 * math.log2(ratio))

    return DimensionScore(
        dimension="signature_size",
        score=round(score, 1),
        weight=SCORE_WEIGHTS["signature_size"],
        weighted_score=round(score * SCORE_WEIGHTS["signature_size"], 2),
        detail=f"Falcon-512 ({pqc_size} B) is {ratio:.1f}x larger than classical ({classical_size} B)",
    )


def _migration_feasibility_score(chain: str) -> DimensionScore:
    """Score based on qualitative migration feasibility assessment."""
    info = MIGRATION_FEASIBILITY[chain]
    return DimensionScore(
        dimension="migration_feasibility",
        score=info["score"],
        weight=SCORE_WEIGHTS["migration_feasibility"],
        weighted_score=round(info["score"] * SCORE_WEIGHTS["migration_feasibility"], 2),
        detail=info["rationale"],
    )


def _zk_readiness_score(chain: str) -> DimensionScore:
    """Score based on chain's readiness for ZK-STARK adoption."""
    info = ZK_READINESS[chain]
    return DimensionScore(
        dimension="zk_readiness",
        score=info["score"],
        weight=SCORE_WEIGHTS["zk_readiness"],
        weighted_score=round(info["score"] * SCORE_WEIGHTS["zk_readiness"], 2),
        detail=info["rationale"],
    )


def _algorithm_diversity_score(chain: str) -> DimensionScore:
    """Score based on how many PQC algorithm families are viable.

    More viable families = more options if one family is broken.
    Viable = retains at least 10% of baseline throughput.
    """
    if chain == "Solana":
        comp = compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC)
    elif chain == "Bitcoin":
        comp = compare_all_bitcoin()
    else:
        comp = compare_all_ethereum()

    # Count PQC families with >10% retention
    families_seen = set()
    for a in comp.analyses:
        if a.signature_type == comp.baseline.signature_type:
            continue
        if a.relative_to_baseline >= 0.10:
            # Determine family
            name = a.signature_type
            if name.startswith("ML-DSA"):
                families_seen.add("ML-DSA")
            elif name.startswith("SLH-DSA"):
                families_seen.add("SLH-DSA")
            elif name.startswith("Falcon"):
                families_seen.add("Falcon")
            elif name.startswith("Hybrid"):
                families_seen.add("Hybrid")

    # 4 possible families: ML-DSA, SLH-DSA, Falcon, Hybrid
    # Score: 25 per viable family
    score = min(100, len(families_seen) * 25)

    return DimensionScore(
        dimension="algorithm_diversity",
        score=float(score),
        weight=SCORE_WEIGHTS["algorithm_diversity"],
        weighted_score=round(score * SCORE_WEIGHTS["algorithm_diversity"], 2),
        detail=f"{len(families_seen)} viable PQC families: {', '.join(sorted(families_seen)) or 'none'}",
    )


def _letter_grade(score: float) -> str:
    """Convert numeric score to letter grade."""
    if score >= 85:
        return "A"
    elif score >= 75:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 45:
        return "D"
    else:
        return "F"


def _recommendation(chain: str, score: float, best_algo: str) -> str:
    """Generate a recommendation based on chain and score."""
    if score >= 75:
        return (
            f"{chain} has strong quantum resistance readiness. "
            f"Recommend adopting {best_algo} as primary PQC signature "
            f"scheme with hybrid classical+PQC during transition."
        )
    elif score >= 55:
        return (
            f"{chain} has moderate quantum resistance readiness. "
            f"{best_algo} is viable but migration challenges exist. "
            f"Prioritize research into protocol-level PQC support."
        )
    else:
        return (
            f"{chain} faces significant quantum resistance challenges. "
            f"{best_algo} preserves throughput but migration path is complex. "
            f"Recommend hybrid schemes and gradual adoption strategy."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_chain(chain: str) -> ChainQRScore:
    """Compute the full quantum resistance score for a blockchain.

    Args:
        chain: "Solana", "Bitcoin", or "Ethereum"

    Returns:
        ChainQRScore with composite score, grade, and dimension breakdown.
    """
    if chain not in ("Solana", "Bitcoin", "Ethereum"):
        raise ValueError(f"Unknown chain: {chain}. Valid: Solana, Bitcoin, Ethereum")

    dimensions = [
        _throughput_retention_score(chain),
        _signature_size_score(chain),
        _migration_feasibility_score(chain),
        _zk_readiness_score(chain),
        _algorithm_diversity_score(chain),
    ]

    composite = sum(d.weighted_score for d in dimensions)

    # Find best PQC algorithm
    if chain == "Solana":
        comp = compare_all_solana(vote_tx_pct=SOLANA_VOTE_TX_PCT_REALISTIC)
    elif chain == "Bitcoin":
        comp = compare_all_bitcoin()
    else:
        comp = compare_all_ethereum()

    pqc = [a for a in comp.analyses if a.signature_type not in CLASSICAL_SIGS]
    best = max(pqc, key=lambda a: a.relative_to_baseline)

    return ChainQRScore(
        chain=chain,
        composite_score=round(composite, 1),
        grade=_letter_grade(composite),
        dimensions=dimensions,
        best_pqc_algorithm=best.signature_type,
        best_pqc_retention=best.relative_to_baseline,
        recommendation=_recommendation(chain, composite, best.signature_type),
    )


def score_all_chains() -> List[ChainQRScore]:
    """Score all three blockchains."""
    return [score_chain(c) for c in ("Solana", "Bitcoin", "Ethereum")]
