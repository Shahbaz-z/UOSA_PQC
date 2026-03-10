"""Ethereum-specific transaction model with gas metering.

Ethereum uses an account model where transactions are metered in gas:
- Base cost: 21,000 gas for a simple ETH transfer
- Calldata: 16 gas per non-zero byte, 4 gas per zero byte
- Signature verification via ecRecover precompile: ~3,000 gas

For PQC analysis, the key distinction is:
1. Gas cost (block capacity): signatures add calldata gas overhead
2. Byte size (propagation): signatures add to the actual bytes on the wire

These can diverge significantly — a PQC signature might add 5,000 gas
(calldata cost) but 2,000+ bytes to propagation.

References:
    - EIP-1559: https://eips.ethereum.org/EIPS/eip-1559
    - Yellow Paper: Gas cost schedule
    - EIP-4844: Blob transactions (separate data availability)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EthereumTxModel:
    """Models account-based transaction with gas metering.

    Attributes:
        base_gas: Intrinsic gas for a simple transfer (21,000).
        calldata_gas_per_nonzero_byte: Gas per non-zero calldata byte (16).
        calldata_gas_per_zero_byte: Gas per zero calldata byte (4).
        sig_verification_gas: ecRecover precompile gas (~3,000).
        avg_calldata_bytes: Average non-signature calldata.
        zero_byte_fraction: Estimated fraction of zero bytes in sig/pk data.
        base_tx_bytes: Base tx bytes (nonce, to, value, gas fields, etc.).
    """

    base_gas: int = 21_000
    calldata_gas_per_nonzero_byte: int = 16
    calldata_gas_per_zero_byte: int = 4
    sig_verification_gas: int = 3_000     # ecRecover or PQC verify precompile
    avg_calldata_bytes: int = 100         # Average additional calldata
    zero_byte_fraction: float = 0.05      # ~5% zero bytes in sig data (conservative)
    base_tx_bytes: int = 120              # nonce(8) + to(20) + value(32) + gas(8) + etc.

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

    def tx_gas(self, sig_size: int, pk_size: int) -> int:
        """Total gas cost including PQC signature overhead.

        Components:
        1. Base gas (21,000)
        2. Signature calldata: sig + pk bytes at calldata rate
        3. Signature verification precompile gas
        4. Average additional calldata

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.

        Returns:
            Total gas cost for the transaction.
        """
        sig_gas = self.calldata_gas(sig_size + pk_size)
        extra_gas = self.calldata_gas(self.avg_calldata_bytes)
        return self.base_gas + sig_gas + self.sig_verification_gas + extra_gas

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

    def txs_per_block(self, sig_size: int, pk_size: int, gas_limit: int = 30_000_000) -> int:
        """Maximum transactions that fit in a block.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.
            gas_limit: Block gas limit (default 30M).

        Returns:
            Number of transactions that fit.
        """
        gas = self.tx_gas(sig_size, pk_size)
        if gas <= 0:
            return 0
        return gas_limit // gas

    def block_bytes(self, sig_size: int, pk_size: int, gas_limit: int = 30_000_000) -> int:
        """Estimated block byte size when filled to gas limit.

        Used for propagation delay calculation.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.
            gas_limit: Block gas limit.

        Returns:
            Total block size in bytes.
        """
        n_txs = self.txs_per_block(sig_size, pk_size, gas_limit)
        return n_txs * self.tx_bytes(sig_size, pk_size)


# Default model instance
DEFAULT_ETHEREUM_TX_MODEL = EthereumTxModel()
