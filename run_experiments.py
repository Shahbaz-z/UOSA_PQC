#!/usr/bin/env python3
"""Phase 2/3 Monte Carlo Parameter Sweep.

Sweeps the PQC AlgorithmMix fraction from 0% to 100% in 5% increments.
For each increment, runs 10 distinct simulation seeds.
Total: 21 × 10 = 210 simulation runs.

Output: results/pqc_sweep.csv

Usage:
    python run_experiments.py [--chain solana] [--duration 5000] [--seeds 10]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from simulator.core.phase2_engine import Phase2Engine, Phase2Config


# ---------------------------------------------------------------------------
# Default sweep parameters
# ---------------------------------------------------------------------------
DEFAULT_CHAIN = "solana"
DEFAULT_LAMBDA_TPS = 4000.0  # Must exceed block capacity under PQC to test saturation
DEFAULT_MEMPOOL_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_NUM_VALIDATORS = 50
DEFAULT_NUM_FULL_NODES = 25
DEFAULT_SIMULATION_DURATION_MS = 10_000  # 10 seconds per run
DEFAULT_NUM_SEEDS = 10
DEFAULT_PQC_STEP = 0.05  # 5% increments


def run_single(
    chain: str,
    pqc_fraction: float,
    seed: int,
    lambda_tps: float,
    mempool_bytes: int,
    num_validators: int,
    num_full_nodes: int,
    duration_ms: float,
) -> Dict:
    """Run a single Phase 2/3 simulation and return results dict."""
    cfg = Phase2Config(
        chain=chain,
        pqc_fraction=pqc_fraction,
        lambda_tps=lambda_tps,
        mempool_capacity_bytes=mempool_bytes,
        num_validators=num_validators,
        num_full_nodes=num_full_nodes,
        simulation_duration_ms=duration_ms,
        random_seed=seed,
    )
    return Phase2Engine(cfg).run()


def flatten_result(result: Dict) -> Dict:
    """Flatten nested dicts (algo_distribution, algo_counts) for CSV."""
    flat = {}
    for key, val in result.items():
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                flat[f"{key}_{sub_key}"] = sub_val
        else:
            flat[key] = val
    return flat


def run_sweep(
    chain: str = DEFAULT_CHAIN,
    lambda_tps: float = DEFAULT_LAMBDA_TPS,
    mempool_bytes: int = DEFAULT_MEMPOOL_BYTES,
    num_validators: int = DEFAULT_NUM_VALIDATORS,
    num_full_nodes: int = DEFAULT_NUM_FULL_NODES,
    duration_ms: float = DEFAULT_SIMULATION_DURATION_MS,
    num_seeds: int = DEFAULT_NUM_SEEDS,
    pqc_step: float = DEFAULT_PQC_STEP,
) -> List[Dict]:
    """Execute the full parameter sweep.

    Returns:
        List of flattened result dictionaries, one per run.
    """
    pqc_fractions = [round(i * pqc_step, 2) for i in range(int(1.0 / pqc_step) + 1)]
    seeds = list(range(1, num_seeds + 1))

    total_runs = len(pqc_fractions) * len(seeds)
    print(f"Parameter sweep: {len(pqc_fractions)} PQC levels × {len(seeds)} seeds = {total_runs} runs")
    print(f"  Chain: {chain}")
    print(f"  λ_tps: {lambda_tps}")
    print(f"  Duration: {duration_ms} ms per run")
    print(f"  Validators: {num_validators}, Full nodes: {num_full_nodes}")
    print(f"  PQC fractions: {pqc_fractions}")
    print()

    all_results: List[Dict] = []
    run_idx = 0
    t_start_total = time.time()

    for pqc_frac in pqc_fractions:
        t_start_level = time.time()
        for seed in seeds:
            run_idx += 1
            t0 = time.time()

            result = run_single(
                chain=chain,
                pqc_fraction=pqc_frac,
                seed=seed,
                lambda_tps=lambda_tps,
                mempool_bytes=mempool_bytes,
                num_validators=num_validators,
                num_full_nodes=num_full_nodes,
                duration_ms=duration_ms,
            )

            elapsed = time.time() - t0
            flat = flatten_result(result)
            all_results.append(flat)

            # Progress: compact per-seed status
            vf = flat.get("verification_failure_rate", 0)
            vt = flat.get("avg_verification_time_ms", 0)
            blocks = flat.get("num_blocks", 0)
            print(
                f"  [{run_idx:3d}/{total_runs}] pqc={pqc_frac:.2f} seed={seed:2d}  "
                f"blocks={blocks:3d}  verify_ms={vt:8.2f}  fail_rate={vf:.4f}  "
                f"({elapsed:.1f}s)"
            )

        level_elapsed = time.time() - t_start_level
        print(f"  → PQC {pqc_frac:.0%} complete ({level_elapsed:.1f}s)\n")

    total_elapsed = time.time() - t_start_total
    print(f"Sweep complete: {total_runs} runs in {total_elapsed:.1f}s ({total_elapsed/total_runs:.2f}s/run)")

    return all_results


def save_csv(results: List[Dict], output_path: str) -> None:
    """Save results to CSV."""
    if not results:
        print("No results to save.")
        return

    # Gather all possible keys (union across all result dicts)
    all_keys = []
    seen = set()
    # Priority keys first, for readable column order
    priority_keys = [
        "chain", "pqc_fraction", "seed", "num_blocks",
        "avg_block_size_bytes", "avg_txs_per_block",
        "avg_propagation_p50_ms", "avg_propagation_p90_ms", "avg_propagation_p95_ms",
        "stale_rate", "effective_tps",
        "avg_verification_time_ms", "max_verification_time_ms",
        "verification_failure_rate", "verification_failures",
        "block_time_ms",
        "mempool_total_accepted", "mempool_total_evicted",
        "mempool_total_rejected", "mempool_final_size_bytes",
        "mempool_final_tx_count", "total_tx_generated",
    ]
    for k in priority_keys:
        if any(k in r for r in results):
            all_keys.append(k)
            seen.add(k)

    # Then add remaining keys alphabetically
    for r in results:
        for k in sorted(r.keys()):
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"Saved {len(results)} rows → {output_path}")
    print(f"Columns: {len(all_keys)}")


def main():
    parser = argparse.ArgumentParser(description="PQC Monte Carlo Parameter Sweep")
    parser.add_argument("--chain", default=DEFAULT_CHAIN, help="Blockchain to simulate")
    parser.add_argument("--lambda-tps", type=float, default=DEFAULT_LAMBDA_TPS)
    parser.add_argument("--mempool-mb", type=int, default=100)
    parser.add_argument("--validators", type=int, default=DEFAULT_NUM_VALIDATORS)
    parser.add_argument("--full-nodes", type=int, default=DEFAULT_NUM_FULL_NODES)
    parser.add_argument("--duration", type=float, default=DEFAULT_SIMULATION_DURATION_MS,
                        help="Simulation duration in ms per run")
    parser.add_argument("--seeds", type=int, default=DEFAULT_NUM_SEEDS)
    parser.add_argument("--pqc-step", type=float, default=DEFAULT_PQC_STEP)
    parser.add_argument("--output", default="results/pqc_sweep.csv")
    args = parser.parse_args()

    results = run_sweep(
        chain=args.chain,
        lambda_tps=args.lambda_tps,
        mempool_bytes=args.mempool_mb * 1024 * 1024,
        num_validators=args.validators,
        num_full_nodes=args.full_nodes,
        duration_ms=args.duration,
        num_seeds=args.seeds,
        pqc_step=args.pqc_step,
    )

    save_csv(results, args.output)


if __name__ == "__main__":
    main()
