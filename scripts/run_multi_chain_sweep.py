#!/usr/bin/env python3
"""Multi-chain Phase 2/3 Monte Carlo Parameter Sweep.

Runs PQC adoption sweeps for Solana, Bitcoin, and Ethereum with
chain-appropriate parameters. Supports the Phase B realism upgrades:
NIC contention and chain-specific routing.

Output: results/<chain>_sweep_v2.csv

Usage:
    python run_multi_chain_sweep.py --chain solana
    python run_multi_chain_sweep.py --chain bitcoin
    python run_multi_chain_sweep.py --chain ethereum
    python run_multi_chain_sweep.py --chain all
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from simulator.core.phase2_engine import Phase2Engine, Phase2Config


# ---------------------------------------------------------------------------
# Chain-specific sweep presets
# ---------------------------------------------------------------------------
CHAIN_PRESETS: Dict[str, Dict] = {
    "solana": {
        "lambda_tps": 4000.0,
        "classical_algo": "Ed25519",
        "num_validators": 50,
        "num_full_nodes": 25,
        "simulation_duration_ms": 10_000,    # 25 slots
        "num_seeds": 10,
        "pqc_step": 0.05,
        "description": "Solana: 400ms slots, Turbine routing, Ed25519 baseline",
    },
    "bitcoin": {
        "lambda_tps": 7.0,                   # ~7 TPS typical
        "classical_algo": "ECDSA",
        "num_validators": 100,               # Full nodes (not PoS validators)
        "num_full_nodes": 50,
        "simulation_duration_ms": 1_200_000, # 2 block times (20 min)
        "num_seeds": 10,
        "pqc_step": 0.10,                    # 10% steps (fewer because slower)
        "description": "Bitcoin: 10-min blocks, compact block relay, ECDSA baseline",
    },
    "ethereum": {
        "lambda_tps": 30.0,                  # ~15-30 TPS
        "classical_algo": "ECDSA",
        "num_validators": 200,
        "num_full_nodes": 100,
        "simulation_duration_ms": 240_000,   # 20 block times (4 min)
        "num_seeds": 10,
        "pqc_step": 0.05,
        "description": "Ethereum: 12s slots, hybrid routing, ECDSA baseline",
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
    """Run a single Phase 2/3 simulation."""
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
    )
    return Phase2Engine(cfg).run()


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
    nic_contention: bool = True,
    use_chain_routing: bool = True,
) -> List[Dict]:
    """Execute parameter sweep for a single chain."""
    preset = CHAIN_PRESETS[chain]
    pqc_step = preset["pqc_step"]
    num_seeds = preset["num_seeds"]

    pqc_fractions = [round(i * pqc_step, 2) for i in range(int(1.0 / pqc_step) + 1)]
    seeds = list(range(1, num_seeds + 1))

    total_runs = len(pqc_fractions) * len(seeds)
    print(f"\n{'=' * 70}")
    print(f"  {preset['description']}")
    print(f"  NIC contention: {nic_contention} | Chain routing: {use_chain_routing}")
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

            # Add realism flags to output
            flat["nic_contention_enabled"] = nic_contention
            flat["use_chain_routing"] = use_chain_routing

            all_results.append(flat)

            stale = flat.get("stale_rate", 0)
            blocks = flat.get("num_blocks", 0)
            p90 = flat.get("avg_propagation_p90_ms", 0)
            print(
                f"  [{run_idx:3d}/{total_runs}] pqc={pqc_frac:.2f} seed={seed:2d}  "
                f"blocks={blocks:3d}  p90={p90:8.1f}ms  stale={stale:.4f}  "
                f"({elapsed:.1f}s)"
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
    parser = argparse.ArgumentParser(description="Multi-Chain PQC Sweep (Phase B)")
    parser.add_argument("--chain", default="solana",
                        choices=["solana", "bitcoin", "ethereum", "all"],
                        help="Chain to simulate (or 'all')")
    parser.add_argument("--no-nic-contention", action="store_true",
                        help="Disable NIC contention (for comparison)")
    parser.add_argument("--no-chain-routing", action="store_true",
                        help="Use basic gossip instead of chain-specific routing")
    parser.add_argument("--output-dir", default="results",
                        help="Output directory for CSV files")
    args = parser.parse_args()

    nic = not args.no_nic_contention
    routing = not args.no_chain_routing

    chains = list(CHAIN_PRESETS.keys()) if args.chain == "all" else [args.chain]

    for chain in chains:
        results = run_chain_sweep(chain, nic_contention=nic, use_chain_routing=routing)

        suffix = "_v2"
        if not nic:
            suffix += "_no_nic"
        if not routing:
            suffix += "_basic_gossip"

        output_path = os.path.join(args.output_dir, f"{chain}_sweep{suffix}.csv")
        save_csv(results, output_path)


if __name__ == "__main__":
    main()
