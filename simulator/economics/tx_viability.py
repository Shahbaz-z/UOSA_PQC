"""Transaction type viability analysis under PQC fee pressure.

Identifies which transaction types become economically unviable (fee > value)
when PQC signature overhead inflates transaction fees.

For small-value transactions (dust payments, micro-tips, small DeFi positions),
the absolute fee increase from PQC signature bloat can exceed the transaction
value itself — making the transaction economically irrational to submit.

This is a pure analytical module (no simulation required):
  - Inputs: SIGNATURE_SIZES from chain_models.py, fee market state, min-value table
  - Output: Per-type viability assessment + breakeven value

References:
    - Bitcoin dust limit: https://github.com/bitcoin/bitcoin/blob/master/src/policy/policy.cpp
    - Ethereum EIP-1559 fee economics: https://eips.ethereum.org/EIPS/eip-1559
    - Solana fee market: https://docs.solana.com/developing/programming-model/runtime
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Transaction type taxonomy
# ---------------------------------------------------------------------------

# Typical transaction values in USD for each type and chain.
# These represent the MINIMUM economically rational transaction value —
# below this, the fee should not exceed the transfer value.
TYPICAL_TX_VALUES_USD: Dict[str, Dict[str, float]] = {
    "bitcoin": {
        "dust_payment":    0.01,    # dust threshold (~546 satoshis at $60k BTC)
        "small_transfer":  10.0,    # everyday small payment
        "medium_transfer": 500.0,   # typical retail transaction
        "exchange_batch":  5_000.0, # exchange withdrawal batch
        "whale_transfer":  50_000.0,
    },
    "ethereum": {
        "erc20_transfer":  1.0,     # small token transfer
        "small_transfer":  20.0,    # ETH small send
        "defi_swap":       100.0,   # typical DeFi interaction
        "nft_mint":        50.0,    # NFT transaction
        "large_transfer":  5_000.0,
    },
    "solana": {
        "spl_transfer":    0.10,    # SPL token micro-transfer
        "small_transfer":  5.0,
        "defi_swap":       50.0,
        "nft_mint":        10.0,
        "large_transfer":  1_000.0,
    },
}

# Max acceptable fee as a fraction of transaction value
# (above this ratio, the transaction is economically irrational)
MAX_FEE_FRACTION: Dict[str, float] = {
    "dust_payment":    0.05,   # 5% fee tolerance for dust
    "small_transfer":  0.02,   # 2% for small transfers
    "medium_transfer": 0.01,
    "exchange_batch":  0.005,
    "whale_transfer":  0.001,
    "erc20_transfer":  0.10,   # higher tolerance for ERC-20 (utility value)
    "defi_swap":       0.05,
    "nft_mint":        0.10,
    "spl_transfer":    0.10,
    "large_transfer":  0.005,
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TxTypeViability:
    """Viability assessment for one transaction type under PQC.

    Attributes:
        tx_type:            Transaction type name.
        chain:              Target chain.
        sig_algorithm:      Signature algorithm.
        tx_size_bytes:      Transaction wire size in bytes.
        estimated_fee_usd:  Estimated absolute fee in USD at current base_fee_rate.
        typical_value_usd:  Typical transaction value for this type.
        max_fee_usd:        Maximum tolerable fee (typical_value × max_fee_fraction).
        fee_fraction:       estimated_fee_usd / typical_value_usd.
        is_viable:          True if estimated_fee_usd ≤ max_fee_usd.
        breakeven_value_usd: Minimum transaction value for which fee is ≤ max_fee_fraction.
        fee_multiplier_vs_classical: fee_fraction relative to the classical baseline.
    """
    tx_type: str
    chain: str
    sig_algorithm: str
    tx_size_bytes: int
    estimated_fee_usd: float
    typical_value_usd: float
    max_fee_usd: float
    fee_fraction: float
    is_viable: bool
    breakeven_value_usd: float
    fee_multiplier_vs_classical: float = 1.0


@dataclass
class ChainViabilityReport:
    """Full viability report for a chain and algorithm combination.

    Attributes:
        chain:           Target chain.
        sig_algorithm:   Signature algorithm.
        base_fee_rate:   Current fee rate (sat/byte, gwei, lamports/CU etc.).
        btc_usd_price:   USD price of the native asset (for fee conversion).
        results:         Per-type viability assessments.
    """
    chain: str
    sig_algorithm: str
    base_fee_rate: float
    btc_usd_price: float
    results: Dict[str, TxTypeViability] = field(default_factory=dict)

    @property
    def viable_types(self) -> List[str]:
        """Transaction types that remain economically viable."""
        return [t for t, v in self.results.items() if v.is_viable]

    @property
    def unviable_types(self) -> List[str]:
        """Transaction types that become uneconomical under PQC fees."""
        return [t for t, v in self.results.items() if not v.is_viable]

    @property
    def viability_fraction(self) -> float:
        """Fraction of transaction types that remain viable."""
        if not self.results:
            return 0.0
        return len(self.viable_types) / len(self.results)

    def summary_table(self) -> str:
        """Markdown table of viability results."""
        lines = [
            f"## Tx Viability: {self.chain.title()} — {self.sig_algorithm}",
            f"Base fee rate: {self.base_fee_rate:.4f}  |  "
            f"Viable types: {len(self.viable_types)}/{len(self.results)}",
            "",
            "| Type | Tx Size (B) | Est. Fee (USD) | Typical Value (USD) "
            "| Fee % | Viable | Break-even (USD) |",
            "|------|------------|---------------|---------------------|"
            "-------|--------|----------------|",
        ]
        for tx_type, v in sorted(self.results.items()):
            status = "✅" if v.is_viable else "❌"
            lines.append(
                f"| {tx_type} | {v.tx_size_bytes:,} | ${v.estimated_fee_usd:.4f} "
                f"| ${v.typical_value_usd:.2f} | {v.fee_fraction*100:.1f}% "
                f"| {status} | ${v.breakeven_value_usd:.2f} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------

def compute_tx_type_viability(
    chain: str,
    sig_algorithm: str,
    base_fee_rate: float,
    native_asset_usd_price: float = 60_000.0,
    classical_algo: Optional[str] = None,
    classical_base_fee_rate: Optional[float] = None,
) -> ChainViabilityReport:
    """Identify which transaction types become uneconomical under PQC fees.

    Args:
        chain:                  Target chain ("bitcoin", "ethereum", "solana").
        sig_algorithm:          PQC (or classical) signature algorithm to analyse.
        base_fee_rate:          Current mempool fee rate.
                                Bitcoin: satoshis/vbyte
                                Ethereum: gwei/gas
                                Solana: lamports/compute_unit
        native_asset_usd_price: USD price of the chain's native asset.
                                Bitcoin: BTC/USD (default $60,000)
                                Ethereum: ETH/USD (pass ~$3,000)
                                Solana: SOL/USD (pass ~$150)
        classical_algo:         Classical baseline for multiplier comparison.
                                If None, uses the chain default.
        classical_base_fee_rate: Classical baseline fee rate for multiplier.
                                If None, same as base_fee_rate (no relative comparison).

    Returns:
        ChainViabilityReport with per-type TxTypeViability assessments.
    """
    from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES

    chain_lower = chain.lower()
    if chain_lower not in TYPICAL_TX_VALUES_USD:
        raise ValueError(f"No viability data for chain: {chain}. "
                         f"Valid: {list(TYPICAL_TX_VALUES_USD)}")

    # Get base tx overhead from chain config
    _OVERHEAD: Dict[str, int] = {
        "bitcoin":  180,   # base UTXO tx overhead (bytes)
        "ethereum": 120,   # base account-model overhead (bytes)
        "solana":   250,   # base Solana tx header (bytes)
    }
    overhead = _OVERHEAD.get(chain_lower, 180)

    sig_size = SIGNATURE_SIZES.get(sig_algorithm, 64)
    pk_size  = PUBLIC_KEY_SIZES.get(sig_algorithm, 32)
    tx_size  = overhead + sig_size + pk_size

    # Classical comparison
    _CLASSICAL_ALGOS = {"bitcoin": "ECDSA", "ethereum": "ECDSA", "solana": "Ed25519"}
    classical = classical_algo or _CLASSICAL_ALGOS.get(chain_lower, "ECDSA")
    classical_sig  = SIGNATURE_SIZES.get(classical, 72)
    classical_pk   = PUBLIC_KEY_SIZES.get(classical, 33)
    classical_size = overhead + classical_sig + classical_pk
    classical_rate = classical_base_fee_rate or base_fee_rate

    # Convert fee to USD
    # Bitcoin: fee_satoshis = fee_rate_sat_vbyte × tx_vbytes → USD = sats / 1e8 × btc_usd
    # Ethereum: fee_gwei = base_fee_gwei × tx_gas; tx_gas ≈ 21000 + calldata
    # Solana: fee_lamports = 5000 base + priority × CUs; CUs ≈ 100 per Ed25519

    def fee_to_usd(size: int, rate: float) -> float:
        """Estimate absolute fee in USD."""
        if chain_lower == "bitcoin":
            # vbytes ≈ bytes for SegWit (witness discount not applied here)
            sats = rate * size
            return sats / 1e8 * native_asset_usd_price

        elif chain_lower == "ethereum":
            # Simple model: gas = 21000 (base) + calldata bytes × 40 (post-Pectra)
            # For the sig/pk portion: (sig_size + pk_size) × 40 gas/byte
            from simulator.chains.ethereum_specific import EthereumTxModel
            eth_model = EthereumTxModel()
            gas = eth_model.tx_gas(
                SIGNATURE_SIZES.get(sig_algorithm, 64),
                PUBLIC_KEY_SIZES.get(sig_algorithm, 32),
                sig_algorithm=sig_algorithm,
            )
            # fee_gwei = rate × gas; convert to USD
            fee_eth = (rate * gas) / 1e9   # gwei → ETH
            return fee_eth * native_asset_usd_price

        elif chain_lower == "solana":
            # Lamports: 5000 base + rate × CUs
            # CUs ≈ 100 for Ed25519; up to 40,000 for SLH-DSA
            from simulator.chains.solana_specific import CU_COSTS
            cus = CU_COSTS.get(sig_algorithm, 8_000)
            lamports = 5_000 + rate * cus
            return lamports / 1e9 * native_asset_usd_price

        else:
            # Generic: fee = rate × size, treat rate as USD/byte
            return rate * size

    tx_types = TYPICAL_TX_VALUES_USD[chain_lower]
    results: Dict[str, TxTypeViability] = {}

    for tx_type, typical_value in tx_types.items():
        max_fee_fraction = MAX_FEE_FRACTION.get(tx_type, 0.02)
        max_fee_usd = typical_value * max_fee_fraction

        estimated_fee    = fee_to_usd(tx_size, base_fee_rate)
        classical_fee    = fee_to_usd(classical_size, classical_rate)
        fee_fraction     = estimated_fee / typical_value if typical_value > 0 else float("inf")
        is_viable        = estimated_fee <= max_fee_usd
        # Break-even: minimum value where fee_fraction ≤ max_fee_fraction
        breakeven_value  = estimated_fee / max_fee_fraction if max_fee_fraction > 0 else float("inf")
        multiplier       = estimated_fee / classical_fee if classical_fee > 0 else 1.0

        results[tx_type] = TxTypeViability(
            tx_type=tx_type,
            chain=chain_lower,
            sig_algorithm=sig_algorithm,
            tx_size_bytes=tx_size,
            estimated_fee_usd=estimated_fee,
            typical_value_usd=typical_value,
            max_fee_usd=max_fee_usd,
            fee_fraction=fee_fraction,
            is_viable=is_viable,
            breakeven_value_usd=breakeven_value,
            fee_multiplier_vs_classical=multiplier,
        )

    return ChainViabilityReport(
        chain=chain_lower,
        sig_algorithm=sig_algorithm,
        base_fee_rate=base_fee_rate,
        btc_usd_price=native_asset_usd_price,
        results=results,
    )


def viability_sweep(
    chain: str,
    algorithms: Optional[List[str]] = None,
    base_fee_rate: float = 20.0,
    native_asset_usd_price: float = 60_000.0,
) -> Dict[str, ChainViabilityReport]:
    """Compute viability reports for multiple algorithms on a single chain.

    Args:
        chain:                  Target chain.
        algorithms:             Algorithms to compare. Defaults to common set.
        base_fee_rate:          Current fee rate (chain-native units).
        native_asset_usd_price: USD price of the native asset.

    Returns:
        Dict mapping algorithm → ChainViabilityReport.
    """
    if algorithms is None:
        algorithms = [
            "ECDSA", "Ed25519",
            "Falcon-512", "Falcon-1024",
            "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
            "SLH-DSA-128s", "SLH-DSA-128f",
        ]

    classical = {"bitcoin": "ECDSA", "ethereum": "ECDSA", "solana": "Ed25519"}.get(chain, "ECDSA")

    reports = {}
    for algo in algorithms:
        reports[algo] = compute_tx_type_viability(
            chain=chain,
            sig_algorithm=algo,
            base_fee_rate=base_fee_rate,
            native_asset_usd_price=native_asset_usd_price,
            classical_algo=classical,
            classical_base_fee_rate=base_fee_rate,
        )
    return reports
