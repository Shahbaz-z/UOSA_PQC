"""Block-Space Visualizer state management."""

from __future__ import annotations

from typing import List, Dict, Any
import reflex as rx

from blockchain.solana_model import (
    compare_all_solana,
    compare_all_bitcoin,
    compare_all_ethereum,
    SOLANA_BLOCK_SIZE_BYTES,
    SOLANA_BASE_TX_OVERHEAD,
    SOLANA_SLOT_TIME_MS,
    BITCOIN_BLOCK_WEIGHT_LIMIT,
    BITCOIN_BASE_TX_OVERHEAD,
    BITCOIN_BLOCK_TIME_MS,
    ETHEREUM_BLOCK_GAS_LIMIT,
    ETHEREUM_BASE_TX_OVERHEAD,
    ETHEREUM_BLOCK_TIME_MS,
    ETHEREUM_GAS_LIMITS,
    SIGNATURE_SIZES,
)


class BlockSpaceState(rx.State):
    """State for Block-Space Visualizer tab."""

    # Chain selection
    chain: str = "Solana"
    num_signers: int = 1

    # Solana parameters
    sol_block_size: int = SOLANA_BLOCK_SIZE_BYTES
    sol_base_overhead: int = SOLANA_BASE_TX_OVERHEAD
    sol_slot_time: int = SOLANA_SLOT_TIME_MS
    sol_vote_pct: int = 0

    # Bitcoin parameters
    btc_block_weight: int = BITCOIN_BLOCK_WEIGHT_LIMIT
    btc_base_overhead: int = BITCOIN_BASE_TX_OVERHEAD
    btc_block_time: int = BITCOIN_BLOCK_TIME_MS

    # Ethereum parameters
    eth_gas_limit: int = ETHEREUM_BLOCK_GAS_LIMIT
    eth_base_overhead: int = ETHEREUM_BASE_TX_OVERHEAD
    eth_block_time: int = ETHEREUM_BLOCK_TIME_MS

    # --- Chain Selection ---

    def set_chain(self, chain: str):
        """Set the active blockchain."""
        self.chain = chain

    def set_num_signers(self, value: list):
        """Set number of signers from slider."""
        if value:
            self.num_signers = int(value[0])

    # --- Solana Parameter Handlers ---

    def set_sol_vote_pct(self, value: list):
        """Set Solana vote transaction percentage."""
        if value:
            self.sol_vote_pct = int(value[0])

    def set_sol_block_size(self, value: str):
        """Set Solana block size."""
        try:
            self.sol_block_size = int(value)
        except ValueError:
            pass

    def set_sol_base_overhead(self, value: str):
        """Set Solana base tx overhead."""
        try:
            self.sol_base_overhead = int(value)
        except ValueError:
            pass

    def set_sol_slot_time(self, value: str):
        """Set Solana slot time."""
        try:
            self.sol_slot_time = int(value)
        except ValueError:
            pass

    # --- Solana Presets ---

    def preset_solana_theoretical(self):
        """Theoretical max: 100% for user txs."""
        self.sol_block_size = SOLANA_BLOCK_SIZE_BYTES
        self.sol_base_overhead = SOLANA_BASE_TX_OVERHEAD
        self.sol_slot_time = SOLANA_SLOT_TIME_MS
        self.sol_vote_pct = 0

    def preset_solana_realistic(self):
        """Realistic: 70% vote overhead."""
        self.sol_block_size = SOLANA_BLOCK_SIZE_BYTES
        self.sol_base_overhead = SOLANA_BASE_TX_OVERHEAD
        self.sol_slot_time = SOLANA_SLOT_TIME_MS
        self.sol_vote_pct = 70

    def preset_solana_high_activity(self):
        """High activity: 80% vote overhead."""
        self.sol_block_size = SOLANA_BLOCK_SIZE_BYTES
        self.sol_base_overhead = SOLANA_BASE_TX_OVERHEAD
        self.sol_slot_time = SOLANA_SLOT_TIME_MS
        self.sol_vote_pct = 80

    def preset_solana_high_throughput(self):
        """High throughput: 12 MB block, no vote overhead."""
        self.sol_block_size = 12_000_000
        self.sol_base_overhead = 200
        self.sol_slot_time = SOLANA_SLOT_TIME_MS
        self.sol_vote_pct = 0

    # --- Bitcoin Parameter Handlers ---

    def set_btc_block_weight(self, value: str):
        """Set Bitcoin block weight."""
        try:
            self.btc_block_weight = int(value)
        except ValueError:
            pass

    def set_btc_base_overhead(self, value: str):
        """Set Bitcoin base tx overhead."""
        try:
            self.btc_base_overhead = int(value)
        except ValueError:
            pass

    def set_btc_block_time(self, value: str):
        """Set Bitcoin block time."""
        try:
            self.btc_block_time = int(value)
        except ValueError:
            pass

    # --- Bitcoin Presets ---

    def preset_bitcoin_default(self):
        """Default Bitcoin parameters."""
        self.btc_block_weight = BITCOIN_BLOCK_WEIGHT_LIMIT
        self.btc_base_overhead = BITCOIN_BASE_TX_OVERHEAD
        self.btc_block_time = BITCOIN_BLOCK_TIME_MS

    def preset_bitcoin_larger(self):
        """Larger blocks: 8 MWU."""
        self.btc_block_weight = 8_000_000
        self.btc_base_overhead = BITCOIN_BASE_TX_OVERHEAD
        self.btc_block_time = BITCOIN_BLOCK_TIME_MS

    def preset_bitcoin_faster(self):
        """Faster blocks: 2.5 minutes."""
        self.btc_block_weight = BITCOIN_BLOCK_WEIGHT_LIMIT
        self.btc_base_overhead = BITCOIN_BASE_TX_OVERHEAD
        self.btc_block_time = 150_000

    # --- Ethereum Parameter Handlers ---

    def set_eth_gas_limit(self, value: str):
        """Set Ethereum gas limit."""
        try:
            self.eth_gas_limit = int(value)
        except ValueError:
            pass

    def set_eth_base_overhead(self, value: str):
        """Set Ethereum base tx overhead."""
        try:
            self.eth_base_overhead = int(value)
        except ValueError:
            pass

    def set_eth_block_time(self, value: str):
        """Set Ethereum block time."""
        try:
            self.eth_block_time = int(value)
        except ValueError:
            pass

    # --- Ethereum Presets ---

    def preset_ethereum_2024(self):
        """2024 baseline: 30M gas."""
        self.eth_gas_limit = ETHEREUM_GAS_LIMITS["2024_baseline"]
        self.eth_base_overhead = ETHEREUM_BASE_TX_OVERHEAD
        self.eth_block_time = ETHEREUM_BLOCK_TIME_MS

    def preset_ethereum_2025(self):
        """2025 current: 36M gas."""
        self.eth_gas_limit = ETHEREUM_GAS_LIMITS["2025_current"]
        self.eth_base_overhead = ETHEREUM_BASE_TX_OVERHEAD
        self.eth_block_time = ETHEREUM_BLOCK_TIME_MS

    def preset_ethereum_2026_q1(self):
        """2026 Q1: 60M gas."""
        self.eth_gas_limit = ETHEREUM_GAS_LIMITS["2026_q1"]
        self.eth_base_overhead = ETHEREUM_BASE_TX_OVERHEAD
        self.eth_block_time = ETHEREUM_BLOCK_TIME_MS

    def preset_ethereum_2026_q2(self):
        """2026 Q2: 80M gas."""
        self.eth_gas_limit = ETHEREUM_GAS_LIMITS["2026_q2"]
        self.eth_base_overhead = ETHEREUM_BASE_TX_OVERHEAD
        self.eth_block_time = ETHEREUM_BLOCK_TIME_MS

    def preset_ethereum_target(self):
        """2026 target: 180M gas."""
        self.eth_gas_limit = ETHEREUM_GAS_LIMITS["2026_target"]
        self.eth_base_overhead = ETHEREUM_BASE_TX_OVERHEAD
        self.eth_block_time = ETHEREUM_BLOCK_TIME_MS

    # --- Computed Properties ---

    @rx.var
    def analysis_results(self) -> List[Dict[str, Any]]:
        """Compute analysis based on current state."""
        if self.chain == "Solana":
            comp = compare_all_solana(
                self.sol_block_size,
                self.sol_base_overhead,
                self.sol_slot_time,
                self.num_signers,
                self.sol_vote_pct / 100,
            )
        elif self.chain == "Bitcoin":
            comp = compare_all_bitcoin(
                self.btc_block_weight,
                self.btc_base_overhead,
                self.btc_block_time,
                num_signers=self.num_signers,
            )
        else:
            comp = compare_all_ethereum(
                self.eth_gas_limit,
                self.eth_base_overhead,
                self.eth_block_time,
                num_signers=self.num_signers,
            )

        return [
            {
                "scheme": a.signature_type,
                "sig_size": a.signature_bytes,
                "tx_size": a.tx_size_bytes,
                "txs_per_block": a.txs_per_block,
                "tps": a.throughput_tps,
                "vs_baseline": round(a.relative_to_baseline * 100, 1),
                "sig_overhead": a.signature_overhead_pct,
            }
            for a in comp.analyses
        ]

    @rx.var
    def baseline_scheme(self) -> str:
        """Get baseline scheme name for current chain."""
        if self.chain == "Solana":
            return "Ed25519"
        return "ECDSA"

    @rx.var
    def baseline_tps(self) -> float:
        """Get baseline TPS."""
        results = self.analysis_results
        baseline = self.baseline_scheme
        for r in results:
            if r["scheme"] == baseline:
                return r["tps"]
        return 0.0

    @rx.var
    def falcon_tps(self) -> float:
        """Get Falcon-512 TPS."""
        for r in self.analysis_results:
            if r["scheme"] == "Falcon-512":
                return r["tps"]
        return 0.0

    @rx.var
    def ml_dsa_tps(self) -> float:
        """Get ML-DSA-65 TPS."""
        for r in self.analysis_results:
            if r["scheme"] == "ML-DSA-65":
                return r["tps"]
        return 0.0

    @rx.var
    def falcon_vs_baseline(self) -> float:
        """Falcon-512 throughput as percentage of baseline."""
        for r in self.analysis_results:
            if r["scheme"] == "Falcon-512":
                return r["vs_baseline"]
        return 0.0

    @rx.var
    def available_space_info(self) -> str:
        """Info about available space after vote overhead."""
        if self.chain == "Solana" and self.sol_vote_pct > 0:
            available = int(self.sol_block_size * (100 - self.sol_vote_pct) / 100)
            return f"Available for user txs: {100 - self.sol_vote_pct}% ({available:,} bytes)"
        return ""

    @rx.var
    def chain_info(self) -> str:
        """Get description for current chain."""
        if self.chain == "Solana":
            return (
                "Solana uses Ed25519 signatures (64 bytes) with ~6 MB practical "
                "block size and 400 ms slot times."
            )
        elif self.chain == "Bitcoin":
            return (
                "Bitcoin uses ECDSA (secp256k1) signatures with a 4 MWU block weight "
                "limit and 10-minute block times. SegWit discount applies."
            )
        else:
            return (
                "Ethereum uses ECDSA (secp256k1) signatures with a gas-based cost model. "
                "21,000 gas base + 16 gas per non-zero byte."
            )
