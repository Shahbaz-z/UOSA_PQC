#!/usr/bin/env python3
"""Enhanced Multi-chain Phase G Monte Carlo Parameter Sweep.

Extends run_multi_chain_sweep.py with:
- Configurable seed count (default 30 for publication quality)
- Longer simulation durations (60s Solana = ~150 blocks)
- Fee market integration
- Vote transaction overhead (Solana)
- Validator economics post-processing
- Statistical hardening (CIs, bootstrap thresholds)

Output:
    results/<chain>_sweep_enhanced.csv
    results/<chain>_summary_stats.csv
    results/calibration/<chain>_validation_table.csv
    results/calibration/<chain>_gap_analysis.md

Usage:
    python run_enhanced_sweep.py --chain solana
    python run_enhanced_sweep.py --chain all --num-seeds 30
    python run_enhanced_sweep.py --chain solana --quick  # 5 seeds, short duration
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from simulator.core.phase2_engine import Phase2Engine, Phase2Config
from simulator.economics.validator_economics import (
    ValidatorEconomicsModel,
    VALIDATOR_PRESETS,
)


# ---------------------------------------------------------------------------
# Enhanced chain presets (Phase G)
# ---------------------------------------------------------------------------
CHAIN_PRESETS: Dict[str, Dict] = {
    "solana": {
        "lambda_tps": 4000.0,
        "classical_algo": "Ed25519",
        "num_validators": 50,
        "num_full_nodes": 25,
        "simulation_duration_ms": 60_000,    # 60s = ~150 slots (Phase G: 6x longer)
        "num_seeds": 30,                     # Phase G: 30 seeds
        "pqc_step": 0.05,
        "fee_market_enabled": True,
        "vote_tx_fraction": 0.30,            # ~30% of block space for votes
        "description": "Solana: 400ms slots, Turbine, Ed25519, fee market + votes",
    },
    "bitcoin": {
        "lambda_tps": 7.0,
        "classical_algo": "ECDSA",
        "num_validators": 100,
        "num_full_nodes": 50,
        "simulation_duration_ms": 3_600_000, # 60min = 6 blocks (Phase G: 3x longer)
        "num_seeds": 30,
        "pqc_step": 0.10,
        "fee_market_enabled": True,
        "vote_tx_fraction": 0.0,
        "description": "Bitcoin: 10-min blocks, compact relay, ECDSA, fee market",
    },
    "ethereum": {
        "lambda_tps": 30.0,
        "classical_algo": "ECDSA",
        "num_validators": 200,
        "num_full_nodes": 100,
        "simulation_duration_ms": 720_000,   # 12min = 60 blocks (Phase G: 3x longer)
        "num_seeds": 30,
        "pqc_step": 0.05,
        "fee_market_enabled": True,
        "vote_tx_fraction": 0.0,
        "description": "Ethereum: 12s slots, hybrid routing, ECDSA, fee market",
    },
}


def run_single(
    chain: str,
    pqc_fraction: float,
    seed: int,
    preset: Dict,
    nic_contention: bool = True,
    use_chain_routing: bool = True,
) -> Dict:
    """Run a single Phase 2/3 + Phase G simulation."""
    cfg = Phase2Config(
        chain=chain,
        pqc_fraction=pqc_fraction,
        lambda_tps=preset["lambda_tps"],
        classical_algo=preset["classical_algo"],
        num_validators=preset["num_validators"],
        num_full_nodes=preset["num_full_nodes"],
        simulation_duration_ms=preset["simulation_duration_ms"],
        random_seed=seed,
        nic_contention_enabled=nic_contention,
        use_chain_routing=use_chain_routing,
        fee_market_enabled=preset.get("fee_market_enabled", False),
        vote_tx_fraction=preset.get("vote_tx_fraction", 0.0),
    )
    result = Phase2Engine(cfg).run()

    # Post-process: add validator economics
    stale_rate = result.get("stale_rate", 0.0)
    if chain in VALIDATOR_PRESETS:
        econ_model = ValidatorEconomicsModel(VALIDATOR_PRESETS[chain])
        econ_metrics = econ_model.compute_metrics(
            stale_rate, preset["num_validators"]
        )
        result.update(econ_metrics)

    return result


def flatten_result(result: Dict) -> Dict:
    """Flatten nested dicts for CSV."""
    flat = {}
    for key, val in result.items():
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                flat[f"{key}_{sub_key}"] = sub_val
        else:
            flat[key] = val
    return flat


def run_chain_sweep(
    chain: str,
    num_seeds: int = 30,
    duration_multiplier: float = 1.0,
    nic_contention: bool = True,
    use_chain_routing: bool = True,
) -> List[Dict]:
    """Execute parameter sweep for a single chain."""
    preset = dict(CHAIN_PRESETS[chain])  # Copy to allow modification
    preset["num_seeds"] = num_seeds
    preset["simulation_duration_ms"] = int(
        preset["simulation_duration_ms"] * duration_multiplier
    )

    pqc_step = preset["pqc_step"]
    pqc_fractions = [round(i * pqc_step, 2) for i in range(int(1.0 / pqc_step) + 1)]
    seeds = list(range(1, num_seeds + 1))

    total_runs = len(pqc_fractions) * num_seeds
    print(f"\n{'=' * 70}")
    print(f"  {preset['description']}")
    print(f"  Seeds: {num_seeds} | Duration: {preset['simulation_duration_ms']}ms")
    print(f"  NIC contention: {nic_contention} | Chain routing: {use_chain_routing}")
    print(f"  Fee market: {preset.get('fee_market_enabled')} | "
          f"Vote fraction: {preset.get('vote_tx_fraction')}")
    print(f"  {len(pqc_fractions)} PQC levels x {num_seeds} seeds = {total_runs} runs")
    print(f"{'=' * 70}\n")

    all_results: List[Dict] = []
    run_idx = 0
    t_start = time.time()

    for pqc_frac in pqc_fractions:
        t_level = time.time()
        for seed in seeds:
            run_idx += 1
            t0 = time.time()

            result = run_single(
                chain=chain,
                pqc_fraction=pqc_frac,
                seed=seed,
                preset=preset,
                nic_contention=nic_contention,
                use_chain_routing=use_chain_routing,
            )

            elapsed = time.time() - t0
            flat = flatten_result(result)

            flat["nic_contention_enabled"] = nic_contention
            flat["use_chain_routing"] = use_chain_routing

            all_results.append(flat)

            stale = flat.get("stale_rate", 0)
            blocks = flat.get("num_blocks", 0)
            p90 = flat.get("avg_propagation_p90_ms", 0)
            econ = flat.get("profit_margin", "N/A")
            print(
                f"  [{run_idx:3d}/{total_runs}] pqc={pqc_frac:.2f} seed={seed:2d}  "
                f"blocks={blocks:3d}  p90={p90:8.1f}ms  stale={stale:.4f}  "
                f"margin={econ}  ({elapsed:.1f}s)"
            )

        level_elapsed = time.time() - t_level
        print(f"  -> PQC {pqc_frac:.0%} complete ({level_elapsed:.1f}s)\n")

    total_elapsed = time.time() - t_start
    print(f"Sweep complete: {total_runs} runs in {total_elapsed:.1f}s")
    return all_results


def save_csv(results: List[Dict], output_path: str) -> None:
    """Save results to CSV."""
    if not results:
        print("No results to save.")
        return

    all_keys = []
    seen = set()
    priority_keys = [
        "chain", "pqc_fraction", "seed", "nic_contention_enabled", "use_chain_routing",
        "num_blocks", "avg_block_size_bytes", "avg_txs_per_block",
        "avg_propagation_p50_ms", "avg_propagation_p90_ms", "avg_propagation_p95_ms",
        "stale_rate", "effective_tps",
        "avg_verification_time_ms", "max_verification_time_ms",
        "verification_failure_rate", "block_time_ms",
        # Phase G: Fee market
        "fee_market_enabled", "base_fee_mean", "base_fee_final",
        "economic_failure_count", "economic_failure_rate",
        "avg_fee_paid", "median_fee_paid",
        # Phase G: Votes
        "vote_tx_fraction_config", "vote_tx_count_per_block",
        "vote_overhead_fraction", "effective_user_tps",
        # Phase G: Validator economics
        "break_even_stale_rate", "profit_margin", "exit_probability",
        "estimated_validator_exits", "remaining_validators_fraction",
    ]
    for k in priority_keys:
        if any(k in r for r in results):
            all_keys.append(k)
            seen.add(k)
    for r in results:
        for k in sorted(r.keys()):
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"Saved {len(results)} rows -> {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Enhanced Multi-Chain PQC Sweep (Phase G)"
    )
    parser.add_argument(
        "--chain", default="solana",
        choices=["solana", "bitcoin", "ethereum", "all"],
        help="Chain to simulate (or 'all')",
    )
    parser.add_argument(
        "--num-seeds", type=int, default=None,
        help="Override seed count (default: 30)",
    )
    parser.add_argument(
        "--duration-multiplier", type=float, default=1.0,
        help="Multiply simulation duration (default: 1.0)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: 5 seeds, 0.2x duration",
    )
    parser.add_argument(
        "--no-nic-contention", action="store_true",
    )
    parser.add_argument(
        "--no-chain-routing", action="store_true",
    )
    parser.add_argument(
        "--output-dir", default="results",
    )
    args = parser.parse_args()

    nic = not args.no_nic_contention
    routing = not args.no_chain_routing

    chains = list(CHAIN_PRESETS.keys()) if args.chain == "all" else [args.chain]

    for chain in chains:
        num_seeds = args.num_seeds or (5 if args.quick else CHAIN_PRESETS[chain]["num_seeds"])
        dur_mult = 0.2 if args.quick else args.duration_multiplier

        results = run_chain_sweep(
            chain,
            num_seeds=num_seeds,
            duration_multiplier=dur_mult,
            nic_contention=nic,
            use_chain_routing=routing,
        )

        output_path = os.path.join(args.output_dir, f"{chain}_sweep_enhanced.csv")
        save_csv(results, output_path)


if __name__ == "__main__":
    main()
