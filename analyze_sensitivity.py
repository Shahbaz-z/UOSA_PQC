#!/usr/bin/env python3
"""Comparative analysis of the three sweep datasets for the sensitivity analysis."""

import pandas as pd
import numpy as np

# Load all three datasets
original = pd.read_csv("results/pqc_sweep.csv")
falcon = pd.read_csv("results/sensitivity_falcon.csv")
mldsa = pd.read_csv("results/sensitivity_mldsa_only.csv")

original["mix"] = "Default (30/50/20)"
falcon["mix"] = "Falcon-dominant (70/20/10)"
mldsa["mix"] = "ML-DSA-only (60/40/0)"

# Key PQC levels for the comparison table
key_levels = [0.0, 0.25, 0.50, 0.75, 1.00]

print("=" * 80)
print("SENSITIVITY ANALYSIS: THREE PQC ALGORITHM MIXES")
print("=" * 80)

# ---------- Block Size ----------
print("\n\n### BLOCK SIZE (KB) ###\n")
print(f"{'PQC %':<8} {'Default':>18} {'Falcon-dom':>18} {'ML-DSA-only':>18}")
print("-" * 64)
for level in key_levels:
    orig_mean = original[original.pqc_fraction == level].avg_block_size_bytes.mean() / 1024
    falc_mean = falcon[falcon.pqc_fraction == level].avg_block_size_bytes.mean() / 1024
    mlds_mean = mldsa[mldsa.pqc_fraction == level].avg_block_size_bytes.mean() / 1024
    print(f"{level:>6.0%}  {orig_mean:>14.1f} KB {falc_mean:>14.1f} KB {mlds_mean:>14.1f} KB")

# ---------- Propagation P90 ----------
print("\n\n### PROPAGATION P90 (ms) ###\n")
print(f"{'PQC %':<8} {'Default':>15} {'Falcon-dom':>15} {'ML-DSA-only':>15}")
print("-" * 55)
for level in key_levels:
    orig_p90 = original[original.pqc_fraction == level].avg_propagation_p90_ms.mean()
    falc_p90 = falcon[falcon.pqc_fraction == level].avg_propagation_p90_ms.mean()
    mlds_p90 = mldsa[mldsa.pqc_fraction == level].avg_propagation_p90_ms.mean()
    print(f"{level:>6.0%}  {orig_p90:>12.1f} ms {falc_p90:>12.1f} ms {mlds_p90:>12.1f} ms")

# ---------- Stale Rate ----------
print("\n\n### STALE RATE (%) ###\n")
print(f"{'PQC %':<8} {'Default':>12} {'Falcon-dom':>12} {'ML-DSA-only':>12}")
print("-" * 46)
stale_levels = [0.0, 0.25, 0.50, 0.75, 0.85, 0.90, 0.95, 1.00]
for level in stale_levels:
    orig_sr = original[original.pqc_fraction == level].stale_rate.mean() * 100
    falc_sr = falcon[falcon.pqc_fraction == level].stale_rate.mean() * 100
    mlds_sr = mldsa[mldsa.pqc_fraction == level].stale_rate.mean() * 100
    print(f"{level:>6.0%}  {orig_sr:>9.1f}% {falc_sr:>9.1f}% {mlds_sr:>9.1f}%")

# ---------- Verification Time ----------
print("\n\n### VERIFICATION TIME (ms) ###\n")
print(f"{'PQC %':<8} {'Default':>15} {'Falcon-dom':>15} {'ML-DSA-only':>15}")
print("-" * 55)
for level in key_levels:
    orig_vt = original[original.pqc_fraction == level].avg_verification_time_ms.mean()
    falc_vt = falcon[falcon.pqc_fraction == level].avg_verification_time_ms.mean()
    mlds_vt = mldsa[mldsa.pqc_fraction == level].avg_verification_time_ms.mean()
    print(f"{level:>6.0%}  {orig_vt:>12.2f} ms {falc_vt:>12.2f} ms {mlds_vt:>12.2f} ms")

# ---------- 100% PQC Summary ----------
print("\n\n### SUMMARY AT 100% PQC ###\n")
for name, df in [("Default (30/50/20)", original), ("Falcon-dom (70/20/10)", falcon), ("ML-DSA-only (60/40/0)", mldsa)]:
    d = df[df.pqc_fraction == 1.0]
    print(f"  {name}:")
    print(f"    Block size:     {d.avg_block_size_bytes.mean()/1024:>8.1f} KB")
    print(f"    P90:            {d.avg_propagation_p90_ms.mean():>8.1f} ms  ({d.avg_propagation_p90_ms.mean()/400*100:.1f}% of slot)")
    print(f"    Stale rate:     {d.stale_rate.mean()*100:>8.1f}%  (std: {d.stale_rate.std()*100:.1f}%)")
    print(f"    Verification:   {d.avg_verification_time_ms.mean():>8.2f} ms")
    print(f"    Ratio vs base:  {d.avg_block_size_bytes.mean() / original[original.pqc_fraction==0].avg_block_size_bytes.mean():.1f}x")
    print()

# ---------- Baseline Calibration ----------
print("\n### BASELINE CALIBRATION (0% PQC) ###\n")
base = original[original.pqc_fraction == 0.0]
print(f"  Simulator 0% PQC stale rate: {base.stale_rate.mean()*100:.1f}%  (std: {base.stale_rate.std()*100:.2f}%)")
print(f"  Solana mainnet slot skip rate (2024-2025): ~5%")
print(f"  Block size at 0% PQC: {base.avg_block_size_bytes.mean()/1024:.1f} KB")
print(f"  P90 at 0% PQC: {base.avg_propagation_p90_ms.mean():.1f} ms ({base.avg_propagation_p90_ms.mean()/400*100:.1f}% of slot)")
print(f"  P50 at 0% PQC: {base.avg_propagation_p50_ms.mean():.1f} ms")

# Check Falcon threshold -- when does stale rate exceed 30%?
print("\n\n### CRITICAL THRESHOLD ANALYSIS ###\n")
for name, df in [("Default", original), ("Falcon", falcon), ("ML-DSA-only", mldsa)]:
    levels = sorted(df.pqc_fraction.unique())
    threshold = None
    for l in levels:
        sr = df[df.pqc_fraction == l].stale_rate.mean()
        if sr >= 0.30 and threshold is None:
            threshold = l
    if threshold is not None:
        print(f"  {name}: 30% stale threshold at ~{threshold:.0%} PQC")
    else:
        max_sr = df.groupby('pqc_fraction').stale_rate.mean().max()
        print(f"  {name}: Never reaches 30% stale rate (max: {max_sr*100:.1f}%)")
