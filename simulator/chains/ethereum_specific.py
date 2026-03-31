"""Ethereum-specific transaction model with PQC-aware gas schedule.

Ethereum uses an account model where transactions are metered in gas:
- Base cost: 21,000 gas for a simple ETH transfer
- Calldata: 16 gas per non-zero byte, 4 gas per zero byte
- Signature verification via precompile (currently ecRecover: ~3,000 gas)

PQC gas schedule methodology:
    PQC verification cost is estimated from liboqs benchmark cycle counts
    multiplied by an empirical gas-per-cycle ratio of 0.06 (calibrated to
    match the existing ecRecover precompile: ~50,000 cycles × 0.06 ≈ 3,000 gas).
    Source: https://openquantumsafe.org/benchmarking/

    EIP-7696 and related draft EIPs propose precompiles for post-quantum
    signature verification. Until finalised, these figures are estimates
    based on NIST PQC cycle counts and the above ratio.

References:
    - EIP-1559: https://eips.ethereum.org/EIPS/eip-1559
    - EIP-4337: https://eips.ethereum.org/EIPS/eip-4337 (Account Abstraction)
    - EIP-7702: https://eips.ethereum.org/EIPS/eip-7702 (AA + PQC migration)
    - Yellow Paper: Gas cost schedule
    - OQS benchmarks: https://openquantumsafe.org/benchmarking/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# PQC verification gas schedule
# ---------------------------------------------------------------------------

# Estimated gas cost for signature verification via a hypothetical EVM precompile.
# Methodology: benchmark_cycles × (gas_per_cycle = 0.06)
#
# Classical reference:
#   ecRecover (ECDSA secp256k1): ~3,000 gas  (Yellow Paper Appendix E)
#   Ed25519 (no native precompile today, EIP-665 proposal): ~3,000 gas est.
#
# PQC estimates based on liboqs verification benchmarks (x86-64, AVX2):
#   https://openquantumsafe.org/benchmarking/
#
# Falcon figures use fast-verify (~1.3M cycles); ML-DSA uses ~4.2M (ML-DSA-65).
# SLH-DSA-128s is very slow (~15M cycles) while 128f trades larger sigs for
# faster verification (~2M cycles).

PQC_VERIFICATION_GAS: Dict[str, int] = {
    # Classical baselines
    "ECDSA":       3_000,     # current ecRecover precompile (Yellow Paper)
    "Schnorr":     3_000,     # BIP 340 Schnorr; similar cycle count to ECDSA
    "Ed25519":     3_000,     # estimated equivalent (EIP-665 proposal target)
    "BLS12-381":   45_000,    # BLS aggregate verify (~750k cycles × 0.06)

    # FIPS 204 — ML-DSA (Dilithium)
    "ML-DSA-44":   180_000,   # ~3.0M cycles × 0.06
    "ML-DSA-65":   250_000,   # ~4.2M cycles × 0.06
    "ML-DSA-87":   350_000,   # ~5.8M cycles × 0.06

    # Falcon (FN-DSA, pending FIPS)
    "Falcon-512":   80_000,   # ~1.3M cycles × 0.06  (fast verify)
    "Falcon-1024":  150_000,  # ~2.5M cycles × 0.06

    # FIPS 205 — SLH-DSA (SPHINCS+)
    "SLH-DSA-128s":  900_000,  # ~15M cycles × 0.06  (very slow verify)
    "SLH-DSA-128f":  120_000,  # ~2.0M cycles × 0.06 (fast variant)
    "SLH-DSA-192s": 1_500_000, # ~25M cycles × 0.06
    "SLH-DSA-192f":  200_000,  # ~3.3M cycles × 0.06
    "SLH-DSA-256s": 2_200_000, # ~37M cycles × 0.06
    "SLH-DSA-256f":  300_000,  # ~5.0M cycles × 0.06

    # Hybrid schemes (classical + PQC, both verified during migration)
    "hybrid_Falcon512_ECDSA":  83_000,   # 3,000 + 80,000
    "hybrid_Falcon1024_ECDSA": 153_000,  # 3,000 + 150,000
    "hybrid_MLDSA44_ECDSA":   183_000,   # 3,000 + 180,000
    "hybrid_MLDSA65_ECDSA":   253_000,   # 3,000 + 250,000
    "hybrid_MLDSA87_ECDSA":   353_000,   # 3,000 + 350,000

    # Hybrid schemes (Ed25519 + PQC, used for non-EVM / consensus layer)
    "Hybrid-Ed25519+Falcon-512":  83_000,
    "Hybrid-Ed25519+Falcon-1024": 153_000,
    "Hybrid-Ed25519+ML-DSA-44":   183_000,
    "Hybrid-Ed25519+ML-DSA-65":   253_000,
    "Hybrid-Ed25519+ML-DSA-87":   353_000,
}

# EIP-4337 Account Abstraction overhead per UserOperation (gas)
# Source: https://eips.ethereum.org/EIPS/eip-4337
AA_USEROPERATION_OVERHEAD_GAS: int = 21_000

# Gas-per-cycle conversion factor (calibrated to ecRecover)
GAS_PER_CYCLE: float = 0.06


def estimate_pqc_gas(benchmark_cycles: int) -> int:
    """Estimate EVM precompile gas cost from benchmark cycle count.

    Args:
        benchmark_cycles: Measured verification cycles on reference hardware.

    Returns:
        Estimated gas cost for an EVM precompile.
    """
    return max(1, int(benchmark_cycles * GAS_PER_CYCLE))


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------

@dataclass
class EthereumTxModel:
    """Models Ethereum account-based transactions with PQC-aware gas metering.

    Attributes:
        base_gas: Intrinsic gas for a simple ETH transfer (21,000).
        calldata_gas_per_nonzero_byte: Gas per non-zero calldata byte.
            Pre-Pectra: 16 gas/byte.  Post-Pectra (EIP-7623): 40 gas/byte for heavy
            calldata.  Default is 40 (current Ethereum mainnet as of 2026).
        calldata_gas_per_zero_byte: Gas per zero calldata byte (4).
        sig_algorithm: Signature algorithm name for gas schedule lookup.
            Defaults to "ECDSA" (backward-compatible with pre-PQC usage).
            Set to a PQC algorithm name to use the PQC gas schedule.
        avg_calldata_bytes: Average non-signature calldata.
        zero_byte_fraction: Estimated fraction of zero bytes in sig/pk data.
        base_tx_bytes: Base tx bytes (nonce, to, value, gas fields, etc.).
        account_abstraction_overhead_gas: EIP-4337 UserOperation overhead gas.
            Add this for AA-based PQC wallets. 0 = standard EOA tx.
    """

    base_gas: int = 21_000
    # EIP-7623 (Pectra, May 2025) raised non-zero calldata to 40 gas/byte for
    # transactions with heavy calldata (floor_cost / floor_data_gas heuristic).
    # PQC signatures live in calldata; post-Pectra Ethereum, the actual gas cost
    # of PQC transactions is ~2.5× higher than this 16 gas/byte model predicts.
    # The model uses pre-Pectra values as a conservative underestimate.
    # Reference: https://eips.ethereum.org/EIPS/eip-7623
    # EIP-7623 (Pectra, May 2025): non-zero calldata for heavy txs costs 40 gas/byte.
    # PQC signatures are 'heavy calldata' by any threshold, so post-Pectra Ethereum
    # PQC gas costs are ~2.5× higher than the pre-Pectra 16 gas/byte model.
    # Default changed to 40 to reflect the current (2026) Ethereum network.
    # To reproduce pre-Pectra analysis, instantiate with calldata_gas_per_nonzero_byte=16.
    # Reference: https://eips.ethereum.org/EIPS/eip-7623
    calldata_gas_per_nonzero_byte: int = 40  # EIP-7623 post-Pectra (was 16 pre-Pectra)
    calldata_gas_per_zero_byte: int = 4
    sig_algorithm: str = "ECDSA"       # Algorithm for PQC gas schedule lookup
    avg_calldata_bytes: int = 100       # Average additional calldata
    zero_byte_fraction: float = 0.05   # ~5% zero bytes in sig data (conservative)
    base_tx_bytes: int = 120           # nonce(8) + to(20) + value(32) + gas(8) + etc.
    account_abstraction_overhead_gas: int = 0  # EIP-4337 overhead; 0 for standard EOA

    @property
    def sig_verification_gas(self) -> int:
        """Signature verification gas for the configured algorithm.

        Looks up PQC_VERIFICATION_GAS schedule. Falls back to 3,000 (ECDSA)
        for unknown algorithms to preserve backward compatibility.
        """
        return PQC_VERIFICATION_GAS.get(self.sig_algorithm, 3_000)

    def calldata_gas(self, data_bytes: int) -> int:
        """Gas cost for calldata bytes.

        Args:
            data_bytes: Number of calldata bytes.

        Returns:
            Gas cost for the calldata.
        """
        zero = int(data_bytes * self.zero_byte_fraction)
        nonzero = data_bytes - zero
        return nonzero * self.calldata_gas_per_nonzero_byte + zero * self.calldata_gas_per_zero_byte

    def tx_gas(
        self,
        sig_size: int,
        pk_size: int,
        sig_algorithm: Optional[str] = None,
    ) -> int:
        """Total gas cost including PQC signature overhead.

        Components:
        1. Base gas (21,000)
        2. Signature calldata: sig + pk bytes at calldata rate
        3. Signature verification precompile gas (PQC schedule)
        4. Average additional calldata
        5. Account abstraction overhead (if configured)

        Args:
            sig_size:      Signature size in bytes.
            pk_size:       Public key size in bytes.
            sig_algorithm: Override algorithm for this call; uses
                           self.sig_algorithm if None.

        Returns:
            Total gas cost for the transaction.
        """
        algo = sig_algorithm or self.sig_algorithm
        verify_gas = PQC_VERIFICATION_GAS.get(algo, 3_000)

        sig_gas   = self.calldata_gas(sig_size + pk_size)
        extra_gas = self.calldata_gas(self.avg_calldata_bytes)
        return (
            self.base_gas
            + sig_gas
            + verify_gas
            + extra_gas
            + self.account_abstraction_overhead_gas
        )

    def dual_sig_gas(
        self,
        classical_algo: str,
        pqc_algo: str,
        classical_sig_size: int,
        classical_pk_size: int,
        pqc_sig_size: int,
        pqc_pk_size: int,
    ) -> int:
        """Gas cost for a hybrid transaction carrying both classical and PQC signatures.

        During the migration period, wallets may need to submit transactions with
        both signature types for backward/forward compatibility.

        Args:
            classical_algo:      Classical algorithm name (e.g. "ECDSA").
            pqc_algo:            PQC algorithm name (e.g. "ML-DSA-65").
            classical_sig_size:  Classical signature size in bytes.
            classical_pk_size:   Classical public key size in bytes.
            pqc_sig_size:        PQC signature size in bytes.
            pqc_pk_size:         PQC public key size in bytes.

        Returns:
            Total gas for a dual-signature transaction.
        """
        classical_verify = PQC_VERIFICATION_GAS.get(classical_algo, 3_000)
        pqc_verify       = PQC_VERIFICATION_GAS.get(pqc_algo, 3_000)

        classical_calldata = self.calldata_gas(classical_sig_size + classical_pk_size)
        pqc_calldata       = self.calldata_gas(pqc_sig_size + pqc_pk_size)
        extra_gas          = self.calldata_gas(self.avg_calldata_bytes)

        return (
            self.base_gas
            + classical_calldata
            + pqc_calldata
            + classical_verify
            + pqc_verify
            + extra_gas
            + self.account_abstraction_overhead_gas
        )

    def tx_bytes(self, sig_size: int, pk_size: int) -> int:
        """Propagation bytes — actual network overhead.

        This is the real byte size transmitted over the wire,
        independent of gas metering.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.

        Returns:
            Total transaction size in bytes.
        """
        return self.base_tx_bytes + sig_size + pk_size + self.avg_calldata_bytes

    def txs_per_block(
        self,
        sig_size: int,
        pk_size: int,
        gas_limit: int = 30_000_000,
        sig_algorithm: Optional[str] = None,
    ) -> int:
        """Maximum transactions that fit in a block.

        Args:
            sig_size:      Signature size in bytes.
            pk_size:       Public key size in bytes.
            gas_limit:     Block gas limit (default 30M).
            sig_algorithm: Override algorithm for gas lookup.

        Returns:
            Number of transactions that fit.
        """
        gas = self.tx_gas(sig_size, pk_size, sig_algorithm=sig_algorithm)
        if gas <= 0:
            return 0
        return gas_limit // gas

    def block_bytes(
        self,
        sig_size: int,
        pk_size: int,
        gas_limit: int = 30_000_000,
        sig_algorithm: Optional[str] = None,
    ) -> int:
        """Estimated block byte size when filled to gas limit.

        Used for propagation delay calculation.

        Args:
            sig_size:      Signature size in bytes.
            pk_size:       Public key size in bytes.
            gas_limit:     Block gas limit.
            sig_algorithm: Override algorithm for gas lookup.

        Returns:
            Total block size in bytes.
        """
        n_txs = self.txs_per_block(sig_size, pk_size, gas_limit, sig_algorithm)
        return n_txs * self.tx_bytes(sig_size, pk_size)

    def gas_overhead_ratio(
        self,
        sig_size: int,
        pk_size: int,
        sig_algorithm: Optional[str] = None,
    ) -> float:
        """Ratio of PQC tx gas to classical ECDSA tx gas.

        Args:
            sig_size:      PQC signature size in bytes.
            pk_size:       PQC public key size in bytes.
            sig_algorithm: PQC algorithm name.

        Returns:
            Gas overhead ratio (1.0 = no overhead, 10.0 = 10× more gas).
        """
        from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
        ecdsa_gas = self.tx_gas(
            SIGNATURE_SIZES.get("ECDSA", 72),
            PUBLIC_KEY_SIZES.get("ECDSA", 33),
            sig_algorithm="ECDSA",
        )
        pqc_gas = self.tx_gas(sig_size, pk_size, sig_algorithm=sig_algorithm)
        return pqc_gas / ecdsa_gas if ecdsa_gas > 0 else float("inf")


# ---------------------------------------------------------------------------
# Module-level default instances
# ---------------------------------------------------------------------------

# Backward-compatible default (ECDSA, no AA overhead) — matches old behaviour
DEFAULT_ETHEREUM_TX_MODEL = EthereumTxModel(sig_algorithm="ECDSA")
