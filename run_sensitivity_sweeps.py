#!/usr/bin/env python3
"""Sensitivity Analysis: Run Monte Carlo sweeps with alternative PQC algorithm mixes.

Sweep A — Falcon-dominant:  70% Falcon-512, 20% ML-DSA-65, 10% SLH-DSA-128f
Sweep B — ML-DSA-only:     60% ML-DSA-44, 40% ML-DSA-65, 0% SLH-DSA

Uses the same parameters as the original sweep (50 validators, 25 full nodes,
10,000 ms per run, 21 PQC levels × 10 seeds = 210 runs per sweep).

Output:
    results/sensitivity_falcon.csv
    results/sensitivity_mldsa_only.csv
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Sweep configurations
# ---------------------------------------------------------------------------
SWEEPS = {
    "falcon": {
        "label": "Falcon-dominant",
        "pqc_weights": {
            "Falcon-512": 0.70,
            "ML-DSA-65": 0.20,
            "SLH-DSA-128f": 0.10,
        },
        "output": "results/sensitivity_falcon.csv",
    },
    "mldsa_only": {
        "label": "ML-DSA-only",
        "pqc_weights": {
            "ML-DSA-44": 0.60,
            "ML-DSA-65": 0.40,
        },
        "output": "results/sensitivity_mldsa_only.csv",
    },
}

# Shared parameters (matching original sweep)
CHAIN = "solana"
LAMBDA_TPS = 4000.0  # Must exceed block capacity under PQC to test saturation
MEMPOOL_BYTES = 100 * 1024 * 1024
NUM_VALIDATORS = 50
NUM_FULL_NODES = 25
DURATION_MS = 10_000
NUM_SEEDS = 10
PQC_STEP = 0.05


def run_single(pqc_fraction: float, seed: int, pqc_weights: Dict[str, float]) -> Dict:
    cfg = Phase2Config(
        chain=CHAIN,
        pqc_fraction=pqc_fraction,
        lambda_tps=LAMBDA_TPS,
        mempool_capacity_bytes=MEMPOOL_BYTES,
        num_validators=NUM_VALIDATORS,
        num_full_nodes=NUM_FULL_NODES,
        simulation_duration_ms=DURATION_MS,
        random_seed=seed,
        pqc_weights=pqc_weights,
    )
    return Phase2Engine(cfg).run()


def flatten_result(result: Dict) -> Dict:
    flat = {}
    for key, val in result.items():
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                flat[f"{key}_{sub_key}"] = sub_val
        else:
            flat[key] = val
    return flat


def run_sweep(sweep_name: str, pqc_weights: Dict[str, float], output_path: str) -> List[Dict]:
    pqc_fractions = [round(i * PQC_STEP, 2) for i in range(int(1.0 / PQC_STEP) + 1)]
    seeds = list(range(1, NUM_SEEDS + 1))
    total_runs = len(pqc_fractions) * len(seeds)

    print(f"\n{'='*60}")
    print(f"Sensitivity Sweep: {sweep_name}")
    print(f"PQC weights: {pqc_weights}")
    print(f"{len(pqc_fractions)} levels × {len(seeds)} seeds = {total_runs} runs")
    print(f"{'='*60}\n")

    all_results = []
    run_idx = 0
    t_start = time.time()

    for pqc_frac in pqc_fractions:
        t_level = time.time()
        for seed in seeds:
            run_idx += 1
            t0 = time.time()
            result = run_single(pqc_frac, seed, pqc_weights)
            elapsed = time.time() - t0
            flat = flatten_result(result)
            all_results.append(flat)

            blocks = flat.get("num_blocks", 0)
            vt = flat.get("avg_verification_time_ms", 0)
            sr = flat.get("stale_rate", 0)
            print(
                f"  [{run_idx:3d}/{total_runs}] pqc={pqc_frac:.2f} seed={seed:2d}  "
                f"blocks={blocks:3d}  verify_ms={vt:8.2f}  stale={sr:.4f}  ({elapsed:.1f}s)"
            )
        print(f"  → PQC {pqc_frac:.0%} complete ({time.time() - t_level:.1f}s)\n")

    total_elapsed = time.time() - t_start
    print(f"Sweep '{sweep_name}' complete: {total_runs} runs in {total_elapsed:.1f}s\n")

    # Save CSV
    if all_results:
        all_keys = []
        seen = set()
        priority_keys = [
            "chain", "pqc_fraction", "seed", "num_blocks",
            "avg_block_size_bytes", "avg_txs_per_block",
            "avg_propagation_p50_ms", "avg_propagation_p90_ms", "avg_propagation_p95_ms",
            "stale_rate", "effective_tps",
            "avg_verification_time_ms", "max_verification_time_ms",
            "verification_failure_rate",
        ]
        for k in priority_keys:
            if any(k in r for r in all_results):
                all_keys.append(k)
                seen.add(k)
        for r in all_results:
            for k in sorted(r.keys()):
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_results)
        print(f"Saved {len(all_results)} rows → {output_path}")

    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", choices=["falcon", "mldsa_only", "both"], default="both")
    args = parser.parse_args()

    sweeps_to_run = list(SWEEPS.keys()) if args.sweep == "both" else [args.sweep]

    for name in sweeps_to_run:
        cfg = SWEEPS[name]
        run_sweep(name, cfg["pqc_weights"], cfg["output"])

    print("\nAll sensitivity sweeps complete.")
