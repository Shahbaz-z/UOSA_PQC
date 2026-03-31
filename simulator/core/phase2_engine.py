"""Phase 2/3 DES Engine: Stochastic PQC Shock + Economic Mempool Eviction.

RELATIONSHIP TO DESEngine
─────────────────────────
Phase2Engine WRAPS DESEngine via composition (not inheritance).
Do NOT replace DESEngine with Phase2Engine — they serve different purposes.
See simulator/core/engine.py for the full engine hierarchy diagram.

  Phase2Engine.__init__() constructs a DESEngine internally and stores
  it as self._engine.  At runtime, Phase2Engine.run() monkey-patches
  two of DESEngine's event handlers:

    _create_block          → self._create_heterogeneous_block
    _handle_block_received → patched_handle_received (per-tx verify)

  After patching, it calls self._engine.run() to execute the event loop,
  then computes extended Phase 2/3 metrics from the result.

ADDED CAPABILITIES (beyond Phase 1 DESEngine)
──────────────────────────────────────────────
  1. PoissonArrivalModel — stochastic transaction generation
  2. GlobalMempool       — bounded 100 MB capacity, fee-rate eviction
  3. AlgorithmMix        — heterogeneous classical + PQC signature blocks
  4. Per-transaction verification — CPU resources locked per sig algorithm
  5. DynamicFeeMarket    — EIP-1559/first-price/priority-fee models
  6. Vote transactions   — Solana-specific block-space overhead injection

CRITICAL PHYSICS CONSTRAINT
────────────────────────────
  When verifying a heterogeneous block, each transaction is iterated
  individually. The CPU core is occupied for the EXACT verification time
  of that transaction's specific signature algorithm.
  This means an SLH-DSA-128f signature (5,940 µs) physically blocks
  a CPU core 100× longer than an Ed25519 signature (60 µs).
"""

from __future__ import annotations

import sys

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# (simpy removed: Phase2Engine uses DESEngine's heapq analytical loop,
#  not SimPy.  SimPy was used in an earlier prototype.)

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.core.events import EventType, Event
from simulator.state import SimulationState
from simulator.results import SimulationResult
from simulator.network.node import Node
from simulator.network.propagation import Block, Transaction
from simulator.mempool import PoissonArrivalModel
from simulator.mempool.mempool import GlobalMempool
from simulator.mempool.algorithm_mix import AlgorithmMixGenerator, AlgorithmMixConfig
from simulator.economics.fee_market import (
    DynamicFeeMarket,
    FeeMarketConfig,
    FEE_MARKET_PRESETS,
)
from simulator.chains.bitcoin_specific import DEFAULT_BITCOIN_TX_MODEL
from simulator.chains.ethereum_specific import DEFAULT_ETHEREUM_TX_MODEL
from blockchain.chain_models import SIGNATURE_SIZES, PUBLIC_KEY_SIZES
from blockchain.verification import VERIFICATION_PROFILES

logger = logging.getLogger(__name__)


@dataclass
class Phase2Config:
    """Configuration for Phase 2/3 extensions on top of SimulationConfig.

    Attributes:
        pqc_fraction: Fraction of transactions using PQC [0.0, 1.0].
        lambda_tps: Poisson arrival rate (transactions per second).
        mempool_capacity_bytes: Bounded mempool size in bytes.
        pqc_weights: Relative weights for PQC algorithm sub-selection.
        classical_algo: Classical baseline signature algorithm.
    """
    chain: str
    pqc_fraction: float = 0.0
    lambda_tps: float = 500.0
    mempool_capacity_bytes: int = 100 * 1024 * 1024  # 100 MB
    classical_algo: str = "Ed25519"
    pqc_weights: Optional[Dict[str, float]] = None

    # Simulation parameters
    num_validators: int = 50
    num_full_nodes: int = 25
    simulation_duration_ms: float = 60_000  # 1 minute
    random_seed: int = 42

    # Override chain block time / size if desired
    block_time_ms: Optional[float] = None
    block_size_limit_bytes: Optional[int] = None

    # Realism flags (Phase B upgrades)
    nic_contention_enabled: bool = True
    use_chain_routing: bool = True

    # Phase G: Fee market
    fee_market_enabled: bool = False
    fee_market_config: Optional[FeeMarketConfig] = None  # None = use chain preset

    # Phase G: Vote transaction overhead (Solana-specific)
    vote_tx_fraction: float = 0.0  # Fraction of block space reserved for votes

    # Phase 4: Heterogeneous agent-based demand model.
    # When True, Phase2Engine replaces the fixed Poisson lambda with agent-driven
    # demand: AgentPool.simulate_block_demand() modulates transaction arrivals
    # based on current fee pressure.  The baseline_fee_rate is the fee at
    # pqc_fraction=0 (set automatically on first slot tick if not provided).
    use_agent_demand_model: bool = False
    agent_pool_size: int = 500       # Number of agents in the pool
    agent_random_seed: int = 0       # 0 = use config.random_seed + 4


class Phase2Engine:
    """Phase 2/3 Simulation Engine with heterogeneous PQC transactions.

    Extends the Phase 1 propagation engine with:
    - Poisson transaction arrivals filling a bounded mempool
    - Fee-rate-based eviction under mempool pressure
    - Heterogeneous signature blocks (mixed classical + PQC)
    - Per-transaction verification with CPU resource locking

    The core event loop remains the same (SLOT_TICK → BLOCK_PROPOSED →
    BLOCK_PROPAGATED → BLOCK_RECEIVED → BLOCK_VALIDATED), but block
    creation now pulls from the mempool and verification iterates
    each transaction individually.
    """

    def __init__(self, config: Phase2Config) -> None:
        # BUG-C FIX: Agent demand model requires the fee market to be enabled.
        # When fee_market_enabled=False, self._fee_market is None and the agent
        # modulation block (`if self._agent_pool is not None and self._fee_market
        # is not None`) is never entered — the pool is constructed but never
        # consulted, silently no-oping the demand model.
        if config.use_agent_demand_model and not config.fee_market_enabled:
            raise ValueError(
                "use_agent_demand_model=True requires fee_market_enabled=True. "
                "The agent demand model modulates transaction arrivals based on "
                "the current fee market rate; without a fee market there is no "
                "rate signal and the agent pool would be constructed but never used."
            )
        self.config = config
        self.rng = random.Random(config.random_seed)

        # Build SimulationConfig for the underlying Phase 1 engine
        self._sim_config = SimulationConfig(
            chain=config.chain,
            signature_algorithm=config.classical_algo,
            num_validators=config.num_validators,
            num_full_nodes=config.num_full_nodes,
            simulation_duration_ms=config.simulation_duration_ms,
            random_seed=config.random_seed,
            block_time_ms=config.block_time_ms,
            block_size_limit_bytes=config.block_size_limit_bytes,
            nic_contention_enabled=config.nic_contention_enabled,
            use_chain_routing=config.use_chain_routing,
        )

        # Construct the Phase 1 engine (network, topology, state)
        self._engine = DESEngine(self._sim_config)

        # BTC-2: Update the routing strategy with the actual PQC fraction.
        # DESEngine constructs routing with pqc_fraction derived from
        # signature_algorithm (0 or 1).  Phase2Engine uses a mixed block
        # (pqc_fraction in [0,1]), so we re-apply the routing with the
        # exact fraction from Phase2Config for accurate compact block sizing.
        if config.use_chain_routing and config.chain.lower() == "bitcoin":
            from simulator.network.routing import get_routing_strategy as _grs
            self._engine.routing = _grs(config.chain,
                                        pqc_adoption_fraction=config.pqc_fraction)

        # Phase 2 components
        self._arrival_model = PoissonArrivalModel(
            lambda_tps=config.lambda_tps,
            rng=random.Random(config.random_seed + 1),
        )

        self._mempool = GlobalMempool(
            capacity_bytes=config.mempool_capacity_bytes,
        )

        mix_config = AlgorithmMixConfig(
            pqc_fraction=config.pqc_fraction,
            classical_algo=config.classical_algo,
            pqc_weights=config.pqc_weights,
        )
        self._algo_mix = AlgorithmMixGenerator(
            config=mix_config,
            rng=random.Random(config.random_seed + 2),
        )

        # Phase G: Fee market
        self._fee_market: Optional[DynamicFeeMarket] = None
        if config.fee_market_enabled:
            fm_config = config.fee_market_config or FEE_MARKET_PRESETS.get(
                config.chain, FeeMarketConfig()
            )
            self._fee_market = DynamicFeeMarket(
                fm_config, rng=random.Random(config.random_seed + 3)
            )

        # Phase G: Vote tracking
        self._vote_txs_generated: int = 0
        self._vote_bytes_total: int = 0

        # Slot time tracking for accurate inter-slot interval calculation.
        # IMPORTANT: patched_handle_slot must use the ACTUAL elapsed interval
        # (current_time - last_slot_time), NOT the nominal block_time_ms constant.
        # Using the nominal constant systematically overcounts transactions when
        # actual slot intervals are longer than block_time_ms (e.g. due to
        # propagation delays and queued events shifting slot boundaries).
        self._last_slot_time_ms: float = 0.0

        # Phase 4: Heterogeneous agent-based demand model
        self._agent_pool = None
        self._agent_baseline_fee_rate: float = 1.0   # calibrated on first slot tick
        self._blocks_elevated: int = 0               # consecutive blocks with fee > 1.5× baseline
        if config.use_agent_demand_model:
            from simulator.economics.user_agents import AgentPool
            seed = config.agent_random_seed or (config.random_seed + 4)
            self._agent_pool = AgentPool(
                chain=config.chain,
                pool_size=config.agent_pool_size,
                seed=seed,
            )

        # Phase 4: Demand feedback accumulators
        self._demand_txs_submitted:  int = 0
        self._demand_txs_abandoned:  int = 0
        self._demand_txs_batched:    int = 0
        self._demand_l2_migrations:  int = 0
        self._demand_reduction_pct_history: list = []

        # Metrics accumulators
        self._blocks_produced: List[Block] = []
        self._total_evictions: int = 0
        self._total_tx_generated: int = 0
        self._economic_rejections: int = 0
        self._verification_times_ms: List[float] = []

    def run(self) -> Dict:
        """Execute the Phase 2/3 simulation.

        Returns:
            Dictionary with comprehensive simulation results including
            propagation, verification, mempool, and failure metrics.
        """
        # Pre-fill mempool with transactions arriving before the first block.
        # Set _last_slot_time_ms to 0.0 so the first patched_handle_slot computes
        # the actual elapsed interval correctly rather than double-counting.
        self._last_slot_time_ms = 0.0
        self._generate_transactions_until(self._engine.block_time_ms)

        # Run the event loop with Phase 2 overrides
        self._engine._create_block = self._create_heterogeneous_block  # type: ignore

        # Monkey-patch the block verification to use per-tx iteration
        original_handle_received = self._engine._handle_block_received

        def patched_handle_received(event: Event) -> None:
            """Override: use per-transaction verification times.

            Replicates the Ethereum two-phase announcement logic from
            DESEngine._handle_block_received so that Phase 2 Ethereum
            simulations correctly model the announcement → full-block-fetch
            latency.  Without this, announcement events would mark
            first_seen_by immediately, systematically underestimating
            Ethereum propagation latency.
            """
            block_hash = event.payload["block_hash"]
            receiver_id = event.payload["receiver_id"]
            receiver = self._engine.topology.get_node(receiver_id)

            block = self._engine.state.get_block_by_hash(block_hash)
            if not block or receiver.has_seen_block(block_hash):
                return

            # Ethereum two-phase retrieval (mirrors DESEngine._handle_block_received)
            is_eth_announcement = event.payload.get("is_eth_announcement", False)
            if is_eth_announcement:
                sender_id = event.payload.get("sender_id")
                sender = (self._engine.topology.get_node(sender_id)
                          if sender_id else None)
                if sender and block:
                    geo_latency = self._engine.topology.sample_latency(
                        sender.config.region, receiver.config.region
                    )
                    effective_bw = min(
                        sender.config.upload_bandwidth_mbps,
                        receiver.config.download_bandwidth_mbps,
                    )
                    if effective_bw > 0:
                        size_megabits = (block.size_bytes * 8) / 1_000_000
                        tx_time_ms = (size_megabits / effective_bw) * 1000
                        # Two geo_latency legs: request (peer→sender) + response download
                        retrieval_time = (
                            self._engine.state.current_time_ms
                            + geo_latency   # announcement → peer
                            + geo_latency   # request leg: peer → sender
                            + tx_time_ms    # full block download
                        )
                        self._engine.state.schedule_event(
                            time_ms=retrieval_time,
                            event_type=EventType.BLOCK_RECEIVED,
                            payload={
                                "block_hash": block_hash,
                                "receiver_id": receiver_id,
                                "sender_id": sender_id,
                                "is_eth_announcement": False,
                            },
                        )
                return  # Wait for full block before recording first_seen_by

            # Bitcoin compact block relay (BIP 152) — mirrors engine.py logic
            is_compact_relay = event.payload.get("is_compact_relay", False)
            if is_compact_relay:
                sender_id = event.payload.get("sender_id")
                sender = (self._engine.topology.get_node(sender_id)
                          if sender_id else None)
                if sender and block:
                    geo_latency = self._engine.topology.sample_latency(
                        sender.config.region, receiver.config.region
                    )
                    effective_bw = min(
                        sender.config.upload_bandwidth_mbps,
                        receiver.config.download_bandwidth_mbps,
                    )
                    if effective_bw > 0:
                        size_megabits = (block.size_bytes * 8) / 1_000_000
                        tx_time_ms = (size_megabits / effective_bw) * 1000
                        retrieval_time = (
                            self._engine.state.current_time_ms
                            + geo_latency   # getblocktxn request leg
                            + tx_time_ms    # full block download
                        )
                        self._engine.state.schedule_event(
                            time_ms=retrieval_time,
                            event_type=EventType.BLOCK_RECEIVED,
                            payload={
                                "block_hash": block_hash,
                                "receiver_id": receiver_id,
                                "sender_id": sender_id,
                                "is_eth_announcement": False,
                                "is_compact_relay": False,
                            },
                        )
                return  # Wait for full block retrieval

            # Full block received: record receipt and schedule verification
            block.first_seen_by[receiver_id] = self._engine.state.current_time_ms
            receiver.mark_block_seen(block_hash, self._engine.state.current_time_ms)

            # CRITICAL: Per-transaction heterogeneous verification
            verify_time = self._compute_heterogeneous_verify_time(
                block, receiver
            )

            # Use CPU scheduling queue: if all cores are busy, queuing adds delay
            completion_time_ms = receiver.schedule_verification(
                arrival_time_ms=self._engine.state.current_time_ms,
                verify_duration_ms=verify_time,
            )

            self._engine.state.schedule_event(
                time_ms=completion_time_ms,
                event_type=EventType.BLOCK_VALIDATED,
                payload={
                    "block_hash": block_hash,
                    "validator_id": receiver_id,
                },
            )

        self._engine._handle_block_received = patched_handle_received  # type: ignore
        self._engine._handlers[EventType.BLOCK_RECEIVED] = patched_handle_received

        # Patch SLOT_TICK to also generate transactions between blocks
        original_handle_slot = self._engine._handle_slot_tick

        def patched_handle_slot(event: Event) -> None:
            # Compute the ACTUAL elapsed time since the previous slot tick.
            # Using the nominal block_time_ms constant here would be incorrect:
            # in a stochastic DES the time between slot events can exceed the
            # nominal block time (e.g. due to propagation delays, queued events,
            # or sub-ms floating-point rounding in the heapq scheduler).
            # Passing the nominal constant causes the mempool to be refilled
            # with a full interval's worth of transactions every slot even when
            # less time has actually elapsed, systematically overcounting
            # total_tx_generated and inflating eviction rates.
            current_time = self._engine.state.current_time_ms
            actual_interval_ms = max(
                0.0, current_time - self._last_slot_time_ms
            )
            # Fall back to nominal interval on the very first slot (where
            # last_slot_time_ms == 0.0 and current_time == 0.0)
            if actual_interval_ms == 0.0:
                actual_interval_ms = self._engine.block_time_ms
            self._last_slot_time_ms = current_time

            # Phase 4: Agent-based demand modulation.
            # If use_agent_demand_model is enabled, use the agent pool to scale
            # the number of transactions generated this slot based on fee pressure.
            if self._agent_pool is not None and self._fee_market is not None:
                current_rate = self._fee_market.base_fee
                # Calibrate baseline on the first real slot tick
                if current_rate > 0 and self._agent_baseline_fee_rate == 1.0:
                    self._agent_baseline_fee_rate = current_rate

                demand = self._agent_pool.simulate_block_demand(
                    current_fee_rate  = current_rate,
                    baseline_fee_rate = self._agent_baseline_fee_rate,
                    sig_algorithm     = self.config.classical_algo,
                    blocks_elevated   = self._blocks_elevated,
                )
                # Accumulate demand metrics
                self._demand_txs_submitted += demand["txs_submitted"]
                self._demand_txs_abandoned += demand["txs_abandoned"]
                self._demand_txs_batched   += demand["txs_batched"]
                self._demand_l2_migrations += demand["l2_migrations"]
                self._demand_reduction_pct_history.append(
                    demand["demand_reduction_pct"]
                )
                # Scale arrival rate by agent submission fraction
                # (demand destruction: fewer agents submit → lower arrival rate)
                submission_rate = max(0.01, demand["submission_rate"])
                effective_interval = actual_interval_ms * submission_rate
            else:
                effective_interval = actual_interval_ms

            self._generate_transactions_until(effective_interval)

            # Phase G: Update fee market using ACTUAL block utilisation.
            # Previous code hardcoded block_util=1.0 ("always full"), causing
            # EIP-1559 to perpetually push fees upward regardless of whether
            # the block was actually full.  Compute real utilisation from the
            # last produced block vs the block size limit.
            if self._fee_market is not None:
                mempool_util = self._mempool.utilization
                if self._blocks_produced:
                    last_block = self._blocks_produced[-1]
                    max_bytes  = self._engine.block_size_limit
                    block_util = (
                        last_block.size_bytes / max_bytes
                        if max_bytes > 0 else 1.0
                    )
                    block_util = max(0.0, min(1.0, block_util))
                else:
                    block_util = 0.0  # No blocks produced yet
                self._fee_market.update_base_fee(
                    current_time_ms=current_time,
                    mempool_utilization=mempool_util,
                    block_utilization=block_util,
                )
                # Track consecutive blocks with elevated fees (> 1.5× baseline)
                # Used by agent model's l2_migration_min_blocks threshold.
                if (self._agent_baseline_fee_rate > 0
                        and self._fee_market.base_fee
                        > 1.5 * self._agent_baseline_fee_rate):
                    self._blocks_elevated += 1
                else:
                    self._blocks_elevated = 0  # reset on fee normalisation
            original_handle_slot(event)

        self._engine._handle_slot_tick = patched_handle_slot  # type: ignore
        self._engine._handlers[EventType.SLOT_TICK] = patched_handle_slot

        # Run the engine
        result = self._engine.run()

        # Compute Phase 2/3 extended metrics
        return self._compute_phase2_results(result)

    def _generate_transactions_until(self, interval_ms: float) -> None:
        """Generate Poisson-arriving transactions for the given interval.

        Fills the mempool with transactions, each with a randomly sampled
        signature algorithm according to the AlgorithmMix distribution.

        Transaction sizes use chain-specific models (Phase G) for accurate
        byte sizing. Fee market integration assigns realistic fees and
        tracks economic failures.

        Phase G additions:
        - Dynamic fee market: fee assignment and economic rejection
        - Vote transaction injection (Solana-specific)
        """
        elapsed_ms = 0.0
        chain = self.config.chain.lower()

        while elapsed_ms < interval_ms:
            inter_arrival = self._arrival_model.next_inter_arrival_ms()
            elapsed_ms += inter_arrival
            # Use strict > (not >=) so a transaction landing exactly at
            # interval_ms belongs to the NEXT interval, not discarded.
            # This follows the standard half-open [0, interval) convention.
            if elapsed_ms > interval_ms:
                break

            # Sample algorithm for this transaction
            algo = self._algo_mix.sample()
            is_pqc = algo not in ("Ed25519", "ECDSA")

            # Chain-specific byte sizing for propagation
            sig_size = SIGNATURE_SIZES.get(algo, 64)
            pk_size = PUBLIC_KEY_SIZES.get(algo, 32)

            if chain == "bitcoin":
                tx_size = DEFAULT_BITCOIN_TX_MODEL.tx_bytes(sig_size, pk_size)
            elif chain == "ethereum":
                tx_size = DEFAULT_ETHEREUM_TX_MODEL.tx_bytes(sig_size, pk_size)
            else:
                prop_overhead = self._engine.chain_config.propagation_tx_overhead_bytes
                if prop_overhead == 0:
                    prop_overhead = self._engine.chain_config.base_tx_overhead
                tx_size = self._algo_mix.tx_size_bytes(algo, prop_overhead)

            # Fee assignment: use fee market if enabled
            if self._fee_market is not None:
                fee = self._fee_market.generate_tx_fee(tx_size, is_pqc=is_pqc)
            else:
                fee = self.rng.randint(100, 50_000)

            tx = Transaction(
                tx_id=f"tx_{self._total_tx_generated}",
                size_bytes=tx_size,
                signature_algorithm=algo,
                num_signatures=1,
                fee_satoshis=fee,
                arrival_time_ms=self._engine.state.current_time_ms + elapsed_ms,
            )

            # Economic failure check
            if self._fee_market is not None:
                if not self._fee_market.check_acceptable(fee, tx_size):
                    self._economic_rejections += 1
                    self._total_tx_generated += 1
                    continue  # Transaction rejected — economic failure

            accepted, evicted = self._mempool.add_transaction(tx)
            self._total_evictions += len(evicted)
            self._total_tx_generated += 1

        # Phase G: Inject vote transactions (Solana only)
        if chain == "solana" and self.config.vote_tx_fraction > 0:
            self._inject_vote_transactions(interval_ms)

    def _inject_vote_transactions(self, interval_ms: float) -> None:
        """Inject vote transactions into the mempool (Solana-specific).

        Solana validators submit vote transactions every slot (~400ms).
        These consume block space and bandwidth but always use Ed25519
        (system program doesn't change during PQC transition).

        Vote transactions:
        - Size: ~1,232 bytes (compressed Solana vote)
        - Algorithm: Ed25519 (always classical)
        - Priority: Very high (must be included)
        """
        # Use vote_tx_size("Ed25519") from solana_specific.py (= 226 bytes).
        # The previous value of 1,232 bytes was the Solana max packet size
        # (SOLANA_MAX_TX_SIZE), not the vote transaction size. Actual Solana
        # vote txs are ~215-250 bytes (base=130 + sig=64 + pk=32).
        # Source: https://docs.solana.com/consensus/vote-transactions
        from simulator.chains.solana_specific import DEFAULT_SOLANA_TX_MODEL as _sol_model
        VOTE_TX_SIZE = _sol_model.vote_tx_size("Ed25519")  # = 226 bytes
        VOTE_FEE = 100_000  # High priority — votes must be included

        # Number of vote txs per interval = num_validators * fraction
        num_votes = int(self.config.num_validators * self.config.vote_tx_fraction)

        for i in range(num_votes):
            tx = Transaction(
                tx_id=f"vote_{self._vote_txs_generated}",
                size_bytes=VOTE_TX_SIZE,
                signature_algorithm="Ed25519",  # Votes always use classical sigs
                num_signatures=1,
                fee_satoshis=VOTE_FEE,
                arrival_time_ms=self._engine.state.current_time_ms,
            )
            accepted, evicted = self._mempool.add_transaction(tx)
            self._total_evictions += len(evicted)
            self._vote_txs_generated += 1
            self._vote_bytes_total += VOTE_TX_SIZE

    def _create_heterogeneous_block(self, proposer: Node) -> Block:
        """Create a block from mempool with heterogeneous signatures.

        Pulls the highest-fee-rate transactions from the mempool up to
        the block size limit. Uses chain-specific capacity models.

        Phase G: Bitcoin uses weight units, Ethereum uses gas.
        """
        chain = self.config.chain.lower()
        max_block_size = self._engine.block_size_limit

        # For mempool selection we use byte size (propagation size)
        # The capacity constraint is chain-specific but mempool stores byte-sized txs
        # Remove the tx-count cap: the byte budget is the real constraint.
        # A cap of 10,000 txs would prematurely cut Solana blocks at half-capacity
        # for small PQC transactions (~300 bytes each: 6 MB / 300 B = 20,000 txs).
        # Use sys.maxsize so only the byte budget binds.
        max_txs = sys.maxsize

        # Select transactions from mempool
        candidates = self._mempool.get_block_candidates(
            max_block_size_bytes=max_block_size,
            max_txs=max_txs,
        )

        # Remove selected transactions from mempool
        for tx in candidates:
            self._mempool.remove_transaction(tx.tx_id)

        # If mempool is empty, create a minimal block
        if not candidates:
            # Generate at least one transaction
            algo = self._algo_mix.sample()
            base_overhead = self._engine.chain_config.base_tx_overhead
            tx_size = self._algo_mix.tx_size_bytes(algo, base_overhead)
            candidates = [
                Transaction(
                    tx_id=f"tx_filler_{self._engine.state.chain_height + 1}",
                    size_bytes=tx_size,
                    signature_algorithm=algo,
                    num_signatures=1,
                    fee_satoshis=self.rng.randint(100, 10_000),
                    arrival_time_ms=self._engine.state.current_time_ms,
                )
            ]

        # Determine the "primary" signature algorithm for the block
        # (most common algorithm in the block, for metadata)
        algo_counts: Dict[str, int] = {}
        for tx in candidates:
            algo_counts[tx.signature_algorithm] = algo_counts.get(
                tx.signature_algorithm, 0
            ) + 1
        primary_algo = max(algo_counts, key=algo_counts.get)  # type: ignore

        # Bug 7 fix: record each included transaction's fee rate into the
        # fee market so the first-price model can set the next block's base
        # fee to min(included fees).  Without this, _last_block_fees was always
        # empty, causing _update_first_price() to decay toward the floor on
        # every block regardless of actual network demand.
        if self._fee_market is not None:
            for tx in candidates:
                if tx.size_bytes > 0:
                    self._fee_market.record_block_fee(
                        tx.fee_satoshis / tx.size_bytes
                    )

        block = Block(
            block_hash=f"block_{self._engine.state.chain_height + 1}",
            parent_hash=self._engine.state.chain_tip_hash,
            height=self._engine.state.chain_height + 1,
            proposer_id=proposer.node_id,
            timestamp_ms=self._engine.state.current_time_ms,
            transactions=candidates,
            signature_algorithm=primary_algo,
        )

        self._blocks_produced.append(block)
        return block

    def _compute_heterogeneous_verify_time(
        self, block: Block, node: Node
    ) -> float:
        """Compute verification time iterating each transaction individually.

        Mirrors the Phase 1 model in Node.verification_time_ms() exactly:
          1. Raw serial time from the catalog (sum over all transactions)
          2. Adjusted for processing_power_factor as a SERIAL speed divisor
             (faster hardware verifies each signature proportionally faster)
          3. Parallelised across cpu_cores (independent work on separate cores)

        This is consistent with Node.schedule_verification() in node.py which
        receives a verify_duration_ms already adjusted for processing_power_factor
        and then distributes across cores via the _core_free_at heap.

        PREVIOUS BUG: The original implementation multiplied cpu_cores ×
        processing_power_factor as a single divisor.  A node with 64 cores and
        processing_power_factor=1.8 would have effective_cores=115.2, massively
        underestimating verification time vs Phase 1.  The two models would
        disagree by up to processing_power_factor × for the same block.

        For a heterogeneous block, mirroring Node.verification_time_ms() exactly:
          total_serial_us  = Σ verify_time_us(tx.algorithm) × tx.num_signatures
          adjusted_us      = total_serial_us / processing_power_factor
          total_ms         = adjusted_us / 1000

        The result is then passed to node.schedule_verification() which distributes
        the job across cpu_cores via the _core_free_at heap — exactly as Phase 1
        does.  Do NOT divide by cpu_cores here; that would double-apply the core
        parallelisation.

        PREVIOUS BUG: The original implementation computed
            effective_cores = cpu_cores × processing_power_factor
        treating them as a single divisor.  This is wrong because:
          1. It conflates a speed factor (power) with a parallelism factor (cores)
          2. A datacenter node with 64 cores × 1.8 speed = 115.2 “effective cores”
             massively underestimates verification time vs Phase 1
          3. Phase 1 never divides by cpu_cores in verification_time_ms()
        """
        total_serial_us = 0.0

        for tx in block.transactions:
            profile = VERIFICATION_PROFILES.get(tx.signature_algorithm)
            if profile:
                # Apply batch_speedup for algorithms that support batch verification
                # (Ed25519: 0.5×; Schnorr: 0.4×; all PQC: 1.0 = no batch standard).
                # This matches compute_block_verification_time() in verification.py
                # which also applies batch_speedup when use_batch=True (the default).
                # Without this, Ed25519 verification was overestimated 2× vs
                # Phase 1's standalone analysis, making PQC look relatively worse.
                verify_us = (
                    profile.verify_time_us * profile.batch_speedup
                    if profile.batch_speedup < 1.0
                    else profile.verify_time_us
                )
                total_serial_us += verify_us * tx.num_signatures
            else:
                # Unknown algo: conservative 500 µs/sig (no batch speedup assumed)
                total_serial_us += 500.0 * tx.num_signatures

        # Mirror Node.verification_time_ms(): divide by speed factor only.
        # schedule_verification() handles the cpu_cores parallelism.
        power_factor = max(0.001, node.config.processing_power_factor)
        adjusted_serial_us = total_serial_us / power_factor
        total_ms           = adjusted_serial_us / 1000.0

        self._verification_times_ms.append(total_ms)
        return total_ms

    def _compute_phase2_results(self, base_result: SimulationResult) -> Dict:
        """Compute extended Phase 2/3 results.

        Returns:
            Dictionary with all Phase 1 metrics plus Phase 2/3 additions.
        """
        mempool_stats = self._mempool.stats()

        # Compute per-block algorithm distribution by transaction COUNT and BYTES.
        # Count-fraction can be misleading: 50% ML-DSA-65 txs by count may use
        # 90%+ of block space because PQC txs are 10-50× larger.  We report both
        # so consumers can distinguish economic adoption from block-space pressure.
        algo_distribution: Dict[str, int] = {}  # tx count per algo
        algo_bytes: Dict[str, int] = {}          # total bytes per algo
        total_block_txs = 0
        total_block_bytes = 0
        for block in self._blocks_produced:
            for tx in block.transactions:
                algo_distribution[tx.signature_algorithm] = (
                    algo_distribution.get(tx.signature_algorithm, 0) + 1
                )
                algo_bytes[tx.signature_algorithm] = (
                    algo_bytes.get(tx.signature_algorithm, 0) + tx.size_bytes
                )
                total_block_txs += 1
                total_block_bytes += tx.size_bytes

        algo_fractions = {
            algo: count / total_block_txs if total_block_txs > 0 else 0.0
            for algo, count in algo_distribution.items()
        }
        # Byte-fraction: fraction of total block bytes consumed per algorithm
        algo_byte_fractions = {
            algo: bts / total_block_bytes if total_block_bytes > 0 else 0.0
            for algo, bts in algo_bytes.items()
        }

        # Average verification time
        avg_verify_ms = (
            sum(self._verification_times_ms) / len(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )
        max_verify_ms = (
            max(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )

        # Network failure detection
        # A block "fails" if verification time exceeds the block interval
        block_time_ms = self._engine.block_time_ms
        verification_failures = sum(
            1 for v in self._verification_times_ms if v > block_time_ms
        )
        # NOTE: _verification_times_ms has one entry per BLOCK_RECEIVED event
        # handled by patched_handle_received (once per block per receiving node).
        # This rate = fraction of block-receipt events where heterogeneous
        # verification exceeded the block time.  It is an upper-bound proxy for
        # the "verification bottleneck" risk, NOT (failures / (blocks × nodes)).
        verification_failure_rate = (
            verification_failures / len(self._verification_times_ms)
            if self._verification_times_ms
            else 0.0
        )

        # Stale rate: blocks where p90 propagation > 90% of block time
        stale_threshold = block_time_ms * 0.9

        return {
            # Phase 1 metrics (from base result)
            "chain": base_result.chain,
            "pqc_fraction": self.config.pqc_fraction,
            "seed": self.config.random_seed,
            "num_blocks": base_result.num_blocks,
            "avg_block_size_bytes": base_result.avg_block_size_bytes,
            "avg_txs_per_block": base_result.avg_txs_per_block,
            "avg_propagation_p50_ms": base_result.avg_propagation_p50_ms,
            "avg_propagation_p90_ms": base_result.avg_propagation_p90_ms,
            "avg_propagation_p95_ms": base_result.avg_propagation_p95_ms,
            "stale_rate": base_result.stale_rate,
            "effective_tps": base_result.effective_tps,

            # Phase 2: Verification metrics
            "avg_verification_time_ms": round(avg_verify_ms, 4),
            "max_verification_time_ms": round(max_verify_ms, 4),
            # verification_failure_rate: fraction of block-receipt events (one per
            # receiving node per block) where heterogeneous verification exceeded
            # block_time_ms.  This is an upper-bound proxy for the verification
            # bottleneck risk, NOT failures / (total_blocks × total_nodes).
            # The precise name would be 'block_receipt_verify_overhead_rate';
            # the original key is preserved for backward compatibility with scripts.
            "verification_failure_rate": round(verification_failure_rate, 6),
            # Alias with a self-documenting name for new analysis code
            "block_receipt_verify_overhead_rate": round(verification_failure_rate, 6),
            "verification_failures": verification_failures,
            "block_time_ms": block_time_ms,

            # Phase 4: Agent-based demand feedback metrics
            "agent_demand_model_enabled": self._agent_pool is not None,
            "blocks_elevated": self._blocks_elevated,
            # txs that agents chose to submit after fee consideration
            "demand_txs_submitted":  self._demand_txs_submitted,
            # txs abandoned because fee exceeded agent max_fee_ratio
            "demand_txs_abandoned":  self._demand_txs_abandoned,
            # txs batched to reduce per-tx fee burden
            "demand_txs_batched":    self._demand_txs_batched,
            # agents that migrated to L2 due to sustained fee pressure
            "demand_l2_migrations":  self._demand_l2_migrations,
            # average demand reduction across all slots (0 = no reduction)
            "avg_demand_reduction_pct": (
                sum(self._demand_reduction_pct_history)
                / len(self._demand_reduction_pct_history)
                if self._demand_reduction_pct_history else 0.0
            ),

            # Phase 3: Mempool metrics
            "mempool_total_accepted": mempool_stats.total_accepted,
            "mempool_total_evicted": mempool_stats.total_evicted,
            "mempool_total_rejected": mempool_stats.total_rejected,
            "mempool_final_size_bytes": mempool_stats.current_size_bytes,
            "mempool_final_tx_count": mempool_stats.current_tx_count,
            "total_tx_generated": self._total_tx_generated,

            # Algorithm distribution in blocks
            # algo_distribution: fraction of transactions BY COUNT per algorithm
            # algo_byte_distribution: fraction of block BYTES per algorithm
            # (use byte fractions for block-space pressure analysis)
            "algo_distribution": algo_fractions,
            "algo_byte_distribution": algo_byte_fractions,
            "algo_counts": algo_distribution,

            # Phase G: Fee market metrics
            **self._compute_fee_market_metrics(),

            # Phase G: Vote overhead metrics
            **self._compute_vote_metrics(),
        }

    def _compute_fee_market_metrics(self) -> Dict:
        """Compute fee market metrics for results.

        IMPORTANT: economic_failure_count and economic_failure_rate are
        authoritative from Phase2Engine._economic_rejections (incremented in
        _generate_transactions_until when check_acceptable() returns False).
        DynamicFeeMarket.metrics() also contains these fields, but they use
        a different denominator (_total_fee_checks, not _total_tx_generated).
        We replace the fee market's versions with Phase2Engine's to avoid
        confusion and double-counting.
        """
        if self._fee_market is None:
            return {
                "fee_market_enabled": False,
                "economic_failure_count": 0,
                "economic_failure_rate": 0.0,
            }

        fm_metrics = self._fee_market.metrics()
        # Remove the fee market's internal economic_failure fields; replace with
        # Phase2Engine's authoritative counts (correct denominator: total_tx_generated).
        fm_metrics.pop("economic_failure_count", None)
        fm_metrics.pop("economic_failure_rate", None)
        fm_metrics["fee_market_enabled"] = True
        fm_metrics["economic_failure_count"] = self._economic_rejections
        fm_metrics["economic_failure_rate"] = (
            self._economic_rejections / self._total_tx_generated
            if self._total_tx_generated > 0
            else 0.0
        )
        return fm_metrics

    def _compute_vote_metrics(self) -> Dict:
        """Compute vote transaction overhead metrics."""
        num_blocks = len(self._blocks_produced)
        if num_blocks == 0:
            return {
                "vote_tx_fraction_config": self.config.vote_tx_fraction,
                "vote_tx_count_total": 0,
                "vote_tx_count_per_block": 0.0,
                "vote_overhead_bytes_total": 0,
                "vote_overhead_bytes_per_block": 0.0,
                "vote_overhead_fraction": 0.0,
                "effective_user_tps": 0.0,
            }

        # Count vote txs in produced blocks
        vote_txs_in_blocks = 0
        vote_bytes_in_blocks = 0
        user_txs_in_blocks = 0
        for block in self._blocks_produced:
            for tx in block.transactions:
                if tx.tx_id.startswith("vote_"):
                    vote_txs_in_blocks += 1
                    vote_bytes_in_blocks += tx.size_bytes
                else:
                    user_txs_in_blocks += 1

        total_block_bytes = sum(b.size_bytes for b in self._blocks_produced)
        sim_duration_s = self.config.simulation_duration_ms / 1000.0

        return {
            "vote_tx_fraction_config": self.config.vote_tx_fraction,
            "vote_tx_count_total": vote_txs_in_blocks,
            "vote_tx_count_per_block": round(vote_txs_in_blocks / num_blocks, 2),
            "vote_overhead_bytes_total": vote_bytes_in_blocks,
            "vote_overhead_bytes_per_block": round(vote_bytes_in_blocks / num_blocks, 2),
            "vote_overhead_fraction": (
                round(vote_bytes_in_blocks / total_block_bytes, 4)
                if total_block_bytes > 0
                else 0.0
            ),
            "effective_user_tps": (
                round(user_txs_in_blocks / sim_duration_s, 2)
                if sim_duration_s > 0
                else 0.0
            ),
        }
