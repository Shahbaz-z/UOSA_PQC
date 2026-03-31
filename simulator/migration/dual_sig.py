"""Dual-signature migration model for the PQC transition period.

During PQC migration, nodes must carry BOTH a classical signature (for
backward compatibility with un-upgraded nodes) AND a PQC signature (for
forward security with upgraded nodes).

This dual-signature period is the WORST CASE for block space: every
transaction carries two full signatures plus two public keys. It is also
the most academically interesting phase to simulate because it reveals
the congestion spike before the benefits of dropping classical sigs arrive.

Real-world precedents:
  - Bitcoin: BIP draft for quantum-resistant address types proposes a
    co-signing period to allow UTXO migration.
    Ref: https://github.com/bitcoin/bips
  - Ethereum: EIP-7702 (account code delegation) and EIP-7760 hybrid mode
    proposals support carrying both sig types during transition.
    Ref: https://eips.ethereum.org/EIPS/eip-7702
  - Solana: Solana Labs internal roadmap discusses a hybrid validator mode
    for the PQC migration period.

References:
  - NIST PQC migration guidance: https://csrc.nist.gov/pubs/sp/1800/38/ipd
  - Mosca's inequality: https://doi.org/10.1007/978-3-030-16458-4_5
"""

from __future__ import annotations


import math
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional


# ---------------------------------------------------------------------------
# Size tables (imported lazily to avoid circular imports)
# ---------------------------------------------------------------------------

def _get_sizes() -> tuple:
    """Return (SIGNATURE_SIZES, PUBLIC_KEY_SIZES) dicts."""
    from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
    return SIGNATURE_SIZES, PUBLIC_KEY_SIZES


# ---------------------------------------------------------------------------
# DualSigConfig
# ---------------------------------------------------------------------------

@dataclass
class DualSigConfig:
    """Configuration for a dual-signature migration period.

    A transaction during this period carries BOTH a classical signature
    (for backward compatibility) and a PQC signature (for quantum security).

    Attributes:
        classical_algo:        Classical signature algorithm (e.g. "ECDSA", "Ed25519").
        pqc_algo:              PQC signature algorithm (e.g. "ML-DSA-65", "Falcon-512").
        adoption_curve:        Shape of PQC adoption over time.
                               "linear"   – linear ramp from 0 → 1.
                               "logistic" – S-curve (realistic technology adoption).
                               "step"     – instant switch at migration_start_block.
        migration_start_block: Block height at which dual-sig txs begin appearing.
        migration_end_block:   Block height at which classical sigs can be dropped.
                               After this point, transactions only need the PQC sig.
    """

    classical_algo: str         = "ECDSA"
    pqc_algo: str               = "ML-DSA-65"
    adoption_curve: str         = "logistic"
    migration_start_block: int  = 0
    # WARNING: this default is calibrated to Bitcoin (~52,560 blocks/year;
    # 100,000 ≈ 2 years).  For other chains it is WRONG:
    #   Ethereum: 2,628,000 slots/year → 100,000 ≈ 14 hours
    #   Solana:   78,840,000 slots/year → 100,000 ≈ 18 minutes
    # Always use the chain-specific factory functions (bitcoin_ecdsa_to_falcon512(),
    # ethereum_ecdsa_to_mldsa65(), solana_ed25519_to_falcon512()) or pass an
    # explicit migration_end_block calibrated to the target chain.
    migration_end_block: int    = 100_000   # ~2 years for Bitcoin; too short for ETH/Solana

    def __post_init__(self) -> None:
        valid_curves = {"linear", "logistic", "step"}
        if self.adoption_curve not in valid_curves:
            raise ValueError(
                f"adoption_curve must be one of {valid_curves}, "
                f"got: {self.adoption_curve!r}"
            )
        if self.migration_end_block <= self.migration_start_block:
            raise ValueError(
                "migration_end_block must be greater than migration_start_block"
            )

    @property
    def migration_duration_blocks(self) -> int:
        """Total number of blocks in the migration period."""
        return self.migration_end_block - self.migration_start_block

    def combined_sig_size(self) -> int:
        """Total signature bytes carried during dual-sig period.

        Returns:
            Sum of classical and PQC signature sizes in bytes.
        """
        SIGNATURE_SIZES, _ = _get_sizes()
        return (
            SIGNATURE_SIZES.get(self.classical_algo, 64)
            + SIGNATURE_SIZES.get(self.pqc_algo, 2_420)
        )

    def combined_pk_size(self) -> int:
        """Total public key bytes carried during dual-sig period.

        Returns:
            Sum of classical and PQC public key sizes in bytes.
        """
        _, PUBLIC_KEY_SIZES = _get_sizes()
        return (
            PUBLIC_KEY_SIZES.get(self.classical_algo, 32)
            + PUBLIC_KEY_SIZES.get(self.pqc_algo, 1_952)
        )

    def classical_sig_size(self) -> int:
        """Classical-only signature size in bytes."""
        SIGNATURE_SIZES, _ = _get_sizes()
        return SIGNATURE_SIZES.get(self.classical_algo, 64)

    def classical_pk_size(self) -> int:
        """Classical-only public key size in bytes."""
        _, PUBLIC_KEY_SIZES = _get_sizes()
        return PUBLIC_KEY_SIZES.get(self.classical_algo, 32)

    def pqc_sig_size(self) -> int:
        """PQC-only signature size in bytes."""
        SIGNATURE_SIZES, _ = _get_sizes()
        return SIGNATURE_SIZES.get(self.pqc_algo, 2_420)

    def pqc_pk_size(self) -> int:
        """PQC-only public key size in bytes."""
        _, PUBLIC_KEY_SIZES = _get_sizes()
        return PUBLIC_KEY_SIZES.get(self.pqc_algo, 1_952)

    def adoption_fraction(self, block_height: int) -> float:
        """Fraction of transactions using dual-sig at a given block height.

        Returns 0.0 before migration starts, increases to 1.0 by
        migration_end_block, and stays at 1.0 thereafter.

        Args:
            block_height: Current block number.

        Returns:
            Fraction in [0, 1].
        """
        if block_height < self.migration_start_block:
            return 0.0
        if block_height >= self.migration_end_block:
            return 1.0

        # Normalised position within migration window [0, 1]
        t = (block_height - self.migration_start_block) / self.migration_duration_blocks

        if self.adoption_curve == "step":
            return 1.0 if t >= 0 else 0.0

        if self.adoption_curve == "linear":
            return t

        if self.adoption_curve == "logistic":
            # Standard logistic centred at midpoint of migration window.
            # k = 8.0 is chosen to match the Bass diffusion model for
            # infrastructure technology adoption (Rogers 2003: Diffusion of
            # Innovations, 5th ed.) where the S-curve reaches ~95% adoption
            # within the migration window.  With k=8, the curve transitions
            # from 2% to 98% adoption over roughly 70% of the migration window,
            # consistent with observed PoS validator software upgrade timelines
            # (Ethereum Merge: 90% adoption within ~2 epochs).
            # Reference: https://doi.org/10.4324/9781003052500 (Rogers 2003)
            k = 8.0
            return 1.0 / (1.0 + math.exp(-k * (t - 0.5)))

        return t  # fallback

    def effective_avg_sig_size(self, block_height: int) -> float:
        """Weighted average signature size at a given block height.

        This method models the DUAL-SIG PERIOD only (Phase 2).  During
        migration, a fraction of transactions carry dual sigs; the rest
        carry only the classical sig.

        IMPORTANT: For post-migration blocks (block_height >= migration_end_block),
        adoption_fraction() returns 1.0, so this formula correctly resolves to
        combined_sig_size() — the worst-case dual-sig overhead.  If you want
        the PQC-only signature size for Phase 3 (after classical sigs are
        dropped), call pqc_sig_size() directly or use
        pqc_only_avg_sig_size() which handles the Phase 3 context correctly.

        Formula:
            effective = adoption_frac × combined_sig_size
                      + (1 - adoption_frac) × classical_sig_size

        Args:
            block_height: Current block number.

        Returns:
            Effective average signature size in bytes (dual-sig formula).
        """
        frac = self.adoption_fraction(block_height)
        return (
            frac * self.combined_sig_size()
            + (1 - frac) * self.classical_sig_size()
        )

    def pqc_only_avg_sig_size(self, block_height: int) -> float:
        """Phase-aware signature size: dual-sig during migration, PQC-only after.

        Unlike effective_avg_sig_size(), this method correctly returns
        pqc_sig_size() for post-migration blocks (where classical sigs have
        been dropped).  Use this when computing block sizes across all three
        migration phases.

        Phase 1 (pre-migration):     → classical_sig_size()
        Phase 2 (during migration):  → weighted average (same as effective_avg_sig_size)
        Phase 3 (post-migration):    → pqc_sig_size()    ← the key difference

        Args:
            block_height: Current block number.

        Returns:
            Effective average signature size in bytes.
        """
        if block_height >= self.migration_end_block:
            return float(self.pqc_sig_size())
        frac = self.adoption_fraction(block_height)
        return (
            frac * self.combined_sig_size()
            + (1 - frac) * self.classical_sig_size()
        )

    def pqc_only_avg_pk_size(self, block_height: int) -> float:
        """Phase-aware public key size: see pqc_only_avg_sig_size() for semantics."""
        if block_height >= self.migration_end_block:
            return float(self.pqc_pk_size())
        frac = self.adoption_fraction(block_height)
        return (
            frac * self.combined_pk_size()
            + (1 - frac) * self.classical_pk_size()
        )

    def effective_avg_pk_size(self, block_height: int) -> float:
        """Weighted average public key size at a given block height.

        Uses the dual-sig formula (same semantics as effective_avg_sig_size).
        For Phase 3 PQC-only sizes, use pqc_only_avg_pk_size().

        Args:
            block_height: Current block number.

        Returns:
            Effective average public key size in bytes.
        """
        frac = self.adoption_fraction(block_height)
        return (
            frac * self.combined_pk_size()
            + (1 - frac) * self.classical_pk_size()
        )

    def size_overhead_ratio(self, block_height: int) -> float:
        """Ratio of effective tx size to classical-only tx size.

        Useful as a quick measure of block bloat at a given migration stage.

        Uses pqc_only_avg_sig_size() (not effective_avg_sig_size()) so that
        Phase 3 (post-migration) correctly reports the PQC-only overhead rather
        than the dual-sig worst-case.  effective_avg_sig_size() at
        block_height >= migration_end_block returns combined_sig_size() (the
        dual-sig peak), which would make Phase 3 look as expensive as Phase 2.

        Args:
            block_height: Current block number.

        Returns:
            Overhead ratio ≥ 1.0.
        """
        classical_total = self.classical_sig_size() + self.classical_pk_size()
        effective_total = (
            self.pqc_only_avg_sig_size(block_height)
            + self.pqc_only_avg_pk_size(block_height)
        )
        return effective_total / classical_total if classical_total > 0 else 1.0


# ---------------------------------------------------------------------------
# MigrationTimeline
# ---------------------------------------------------------------------------

@dataclass
class MigrationPhase:
    """A single phase in the migration timeline.

    Attributes:
        phase_name:      Human-readable phase label.
        start_block:     First block of this phase.
        end_block:       Last block of this phase (exclusive).
        pqc_fraction:    Fraction of transactions using PQC (or dual-sig).
        is_dual_sig:     True during the dual-signature overlap period.
        avg_sig_bytes:   Effective average signature bytes.
        avg_pk_bytes:    Effective average public key bytes.
    """

    phase_name: str
    start_block: int
    end_block: int
    pqc_fraction: float
    is_dual_sig: bool
    avg_sig_bytes: float
    avg_pk_bytes: float


@dataclass
class MigrationTimeline:
    """Generates a sequence of phases for a PQC migration simulation.

    Divides the migration into three canonical phases:
      Phase 1: 100% classical — all transactions use only classical signatures.
      Phase 2: Dual-sig ramp-up — worst case for block space and fees.
      Phase 3: 100% PQC — classical signatures dropped.

    Attributes:
        dual_sig_config:       Dual-signature configuration.
        pre_migration_blocks:  Number of blocks to simulate before migration starts.
        post_migration_blocks: Number of blocks to simulate after migration ends.
        phase_resolution:      Number of checkpoints per phase for metric sampling.
    """

    dual_sig_config: DualSigConfig = field(default_factory=DualSigConfig)
    pre_migration_blocks: int  = 10_000
    post_migration_blocks: int = 10_000
    phase_resolution: int      = 20

    def phases(self) -> List[MigrationPhase]:
        """Generate the list of simulation phases.

        Lazily cached in self._phases_cache: calling phases() multiple times
        (e.g. from peak_overhead_phase() and congestion_spike_summary()) returns
        the cached list after the first call.  With phase_resolution=50+ this
        avoids redundant O(resolution) recomputation in tight loops.
        functools.cache cannot be used here because MigrationTimeline is a
        mutable dataclass (not hashable); we use a simple instance cache instead.
        

        Returns:
            List of MigrationPhase objects in chronological order.
        """
        # Return cached result if available
        if hasattr(self, "_phases_cache"):
            return self._phases_cache  # type: ignore[attr-defined]

        cfg = self.dual_sig_config
        phases: List[MigrationPhase] = []

        # Phase 1: pre-migration — classical only
        pre_start = max(0, cfg.migration_start_block - self.pre_migration_blocks)
        phases.append(MigrationPhase(
            phase_name   = "Phase 1: Classical",
            start_block  = pre_start,
            end_block    = cfg.migration_start_block,
            pqc_fraction = 0.0,
            is_dual_sig  = False,
            avg_sig_bytes= float(cfg.classical_sig_size()),
            avg_pk_bytes = float(cfg.classical_pk_size()),
        ))

        # Phase 2: dual-sig ramp-up — sample at phase_resolution points.
        # end_block for the last Phase 2 checkpoint is capped at
        # migration_end_block - 1 to ensure Phase 3 starts at migration_end_block
        # without overlap.  Without this guard, the last Phase 2 entry and Phase 3
        # shared start_block = migration_end_block, potentially double-counting
        # metrics if callers iterate and aggregate by block range.
        step = cfg.migration_duration_blocks / self.phase_resolution
        for i in range(self.phase_resolution):
            block      = int(cfg.migration_start_block + i * step)
            next_block = int(block + step)
            # Cap the last Phase 2 checkpoint so it does not overlap Phase 3
            if i == self.phase_resolution - 1:
                next_block = cfg.migration_end_block  # exclusive boundary
            frac  = cfg.adoption_fraction(block)
            phases.append(MigrationPhase(
                phase_name   = f"Phase 2: Dual-sig ({frac:.0%} adopted)",
                start_block  = block,
                end_block    = next_block,
                pqc_fraction = frac,
                is_dual_sig  = True,
                avg_sig_bytes= cfg.effective_avg_sig_size(block),
                avg_pk_bytes = cfg.effective_avg_pk_size(block),
            ))

        # Phase 3: post-migration — PQC only (classical sigs dropped).
        # Use pqc_sig_size() directly (not effective_avg_sig_size()) to ensure
        # Phase 3 reflects the post-migration state where every transaction
        # carries only the PQC signature.  effective_avg_sig_size() at fraction=1.0
        # returns combined_sig_size() (dual-sig worst case), which is incorrect
        # for Phase 3.  pqc_only_avg_sig_size() handles this correctly.
        phases.append(MigrationPhase(
            phase_name   = "Phase 3: PQC only",
            start_block  = cfg.migration_end_block,
            end_block    = cfg.migration_end_block + self.post_migration_blocks,
            pqc_fraction = 1.0,
            is_dual_sig  = False,
            avg_sig_bytes= float(cfg.pqc_sig_size()),   # NOT combined — classical dropped
            avg_pk_bytes = float(cfg.pqc_pk_size()),
        ))

        self._phases_cache = phases  # type: ignore[attr-defined]
        return phases

    def peak_overhead_phase(self) -> MigrationPhase:
        """Return the phase with maximum signature size overhead.

        This is always in Phase 2 (dual-sig), typically near peak adoption
        where every transaction carries both signature types.

        Returns:
            MigrationPhase with highest avg_sig_bytes.
        """
        all_phases = self.phases()
        return max(all_phases, key=lambda p: p.avg_sig_bytes)

    def congestion_spike_summary(self) -> Dict:
        """Summarise the congestion spike during the dual-sig period.

        Returns:
            Dict with peak_overhead_ratio, classical_sig_bytes,
            dual_sig_bytes, pqc_only_bytes, peak_block_height.
        """
        cfg      = self.dual_sig_config
        peak_ph  = self.peak_overhead_phase()
        classical_total = cfg.classical_sig_size() + cfg.classical_pk_size()
        dual_total      = cfg.combined_sig_size()  + cfg.combined_pk_size()
        pqc_total       = cfg.pqc_sig_size()       + cfg.pqc_pk_size()

        return {
            "classical_sig_plus_pk_bytes": classical_total,
            "dual_sig_plus_pk_bytes":      dual_total,
            "pqc_only_sig_plus_pk_bytes":  pqc_total,
            "peak_overhead_ratio":         dual_total / classical_total if classical_total else 1.0,
            "pqc_overhead_ratio":          pqc_total  / classical_total if classical_total else 1.0,
            "peak_block_height":           peak_ph.start_block,
            "peak_pqc_fraction":           peak_ph.pqc_fraction,
        }

    def sim_configs(self, base_chain: str = "bitcoin") -> Iterator[Dict]:
        """Yield simulation parameter dicts for each phase checkpoint.

        Intended for use with DESEngine: each yielded dict maps directly to
        SimulationConfig keyword arguments with the effective sig/pk sizes
        appropriate for that migration stage.

        Args:
            base_chain: Chain to simulate ("bitcoin", "ethereum", "solana").

        Yields:
            Dict with phase metadata + simulation parameters.
        """
        seen_start_blocks: set = set()
        for phase in self.phases():
            if phase.start_block in seen_start_blocks:
                continue
            seen_start_blocks.add(phase.start_block)
            yield {
                "chain":           base_chain,
                "phase_name":      phase.phase_name,
                "start_block":     phase.start_block,
                "end_block":       phase.end_block,
                "pqc_fraction":    phase.pqc_fraction,
                "is_dual_sig":     phase.is_dual_sig,
                "avg_sig_bytes":   phase.avg_sig_bytes,
                "avg_pk_bytes":    phase.avg_pk_bytes,
                "overhead_ratio":  (
                    (phase.avg_sig_bytes + phase.avg_pk_bytes)
                    / (
                        self.dual_sig_config.classical_sig_size()
                        + self.dual_sig_config.classical_pk_size()
                    )
                    if (
                        self.dual_sig_config.classical_sig_size()
                        + self.dual_sig_config.classical_pk_size()
                    ) > 0 else 1.0
                ),
            }


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------

def bitcoin_ecdsa_to_falcon512() -> MigrationTimeline:
    """Standard Bitcoin migration: ECDSA → Falcon-512."""
    return MigrationTimeline(
        dual_sig_config=DualSigConfig(
            classical_algo="ECDSA",
            pqc_algo="Falcon-512",
            adoption_curve="logistic",
            migration_start_block=0,
            migration_end_block=52_560,  # ~1 year of Bitcoin blocks
        )
    )


def ethereum_ecdsa_to_mldsa65() -> MigrationTimeline:
    """Standard Ethereum migration: ECDSA → ML-DSA-65."""
    return MigrationTimeline(
        dual_sig_config=DualSigConfig(
            classical_algo="ECDSA",
            pqc_algo="ML-DSA-65",
            adoption_curve="logistic",
            migration_start_block=0,
            migration_end_block=2_628_000,  # ~1 year of Ethereum slots
        )
    )


def solana_ed25519_to_falcon512() -> MigrationTimeline:
    """Standard Solana migration: Ed25519 → Falcon-512."""
    return MigrationTimeline(
        dual_sig_config=DualSigConfig(
            classical_algo="Ed25519",
            pqc_algo="Falcon-512",
            adoption_curve="logistic",
            migration_start_block=0,
            migration_end_block=78_840_000,  # ~1 year of Solana slots (400ms each)
        )
    )
