"""Bitcoin-specific transaction model with UTXO and SegWit witness discount.

Bitcoin transactions use the UTXO (Unspent Transaction Output) model:
- Each tx consumes inputs (references to prior outputs) and creates new outputs
- SegWit separates signature (witness) data from base transaction data
- Witness data counts at 25% weight (1 byte = 1 weight unit vs 4 for base)

This means PQC signatures, which live in witness data, get a 75% discount
on their contribution to block weight — a significant buffer against
signature size inflation.

References:
    - BIP 141 (SegWit): https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki
    - BIP 152 (Compact Blocks): https://github.com/bitcoin/bips/blob/master/bip-0152.mediawiki
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BitcoinTxModel:
    """Models UTXO-based transaction sizing with SegWit witness discount.

    Attributes:
        avg_inputs: Average number of inputs per transaction.
        avg_outputs: Average number of outputs per transaction.
        witness_discount: Weight multiplier for witness data (0.25 = 75% discount).
    """

    avg_inputs: int = 2
    avg_outputs: int = 2
    witness_discount: float = 0.25  # Witness byte = 0.25 weight units

    # Fixed sizes (bytes)
    VERSION_BYTES: int = 4           # nVersion
    LOCKTIME_BYTES: int = 4          # nLockTime
    INPUT_PREVOUT_BYTES: int = 36    # txid(32) + vout(4)
    INPUT_SEQUENCE_BYTES: int = 4    # nSequence
    INPUT_SCRIPTLEN_BYTES: int = 1   # scriptSig length (0 for SegWit)
    OUTPUT_VALUE_BYTES: int = 8      # value
    OUTPUT_SCRIPT_BYTES: int = 26    # Typical P2WPKH scriptPubKey (1+1+20+1+1+2)
    WITNESS_ITEM_OVERHEAD: int = 2   # witness item count + stack item lengths

    def base_size(self, sig_size: int = 0, pk_size: int = 0) -> int:
        """Non-witness transaction size in bytes.

        For SegWit transactions, the scriptSig is empty (signatures
        are in the witness). Base size is just structure + outputs.

        Args:
            sig_size: Signature size (unused for base; sigs are in witness).
            pk_size: Public key size (unused for base).

        Returns:
            Base transaction size in bytes.
        """
        # Version + marker + flag
        header = self.VERSION_BYTES + self.LOCKTIME_BYTES + 2  # +2 for varint counts

        # Inputs: prevout + sequence + empty scriptSig
        inputs = self.avg_inputs * (
            self.INPUT_PREVOUT_BYTES
            + self.INPUT_SEQUENCE_BYTES
            + self.INPUT_SCRIPTLEN_BYTES  # 0x00 for SegWit
        )

        # Outputs: value + scriptPubKey
        outputs = self.avg_outputs * (
            self.OUTPUT_VALUE_BYTES + self.OUTPUT_SCRIPT_BYTES
        )

        return header + inputs + outputs

    def witness_size(self, sig_size: int, pk_size: int) -> int:
        """Witness data size in bytes.

        Each input has a witness field containing the signature and public key.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.

        Returns:
            Total witness data size in bytes.
        """
        per_input = sig_size + pk_size + self.WITNESS_ITEM_OVERHEAD
        return self.avg_inputs * per_input

    def tx_weight(self, sig_size: int, pk_size: int) -> int:
        """Compute transaction weight units (SegWit accounting).

        Weight = base_size * 4 + witness_size * 1

        The block weight limit is 4,000,000 WU. This formula gives
        witness data a 75% discount compared to base data.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.

        Returns:
            Transaction weight in weight units.
        """
        base = self.base_size(sig_size, pk_size)
        witness = self.witness_size(sig_size, pk_size)
        return base * 4 + witness

    def tx_bytes(self, sig_size: int, pk_size: int) -> int:
        """Actual bytes transmitted over the wire (no discount).

        This is the real network overhead for propagation calculations.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.

        Returns:
            Total transaction size in bytes.
        """
        return self.base_size(sig_size, pk_size) + self.witness_size(sig_size, pk_size)

    def txs_per_block(self, sig_size: int, pk_size: int, block_weight_limit: int = 4_000_000) -> int:
        """Maximum transactions that fit in a block.

        Args:
            sig_size: Signature size in bytes.
            pk_size: Public key size in bytes.
            block_weight_limit: Block weight limit in WU (default 4M).

        Returns:
            Number of transactions that fit.
        """
        weight = self.tx_weight(sig_size, pk_size)
        if weight <= 0:
            return 0
        return block_weight_limit // weight


# Default model instance
DEFAULT_BITCOIN_TX_MODEL = BitcoinTxModel()
