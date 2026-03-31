#!/usr/bin/env python3
"""Chain-specific PQC impact analysis runner.

Generates publication-ready CSV tables and markdown summaries for:
  - Bitcoin: block capacity, witness policies, fee market dynamics
  - Ethereum: gas costs, EIP-1559, consensus layer, validator economics
  - Migration: transition curves for both chains

Usage:
    python run_chain_analysis.py                     # All chains, all algorithms
    python run_chain_analysis.py --chain btc          # Bitcoin only
    python run_chain_analysis.py --chain eth          # Ethereum only
    python run_chain_analysis.py --algorithms falcon   # FALCON family only
    python run_chain_analysis.py --chain all --algorithms all
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import os
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
os.chdir(_project_root)
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis.pqc_algorithms import (
    ALL_ALGORITHMS,
    ECDSA,
    FAMILY_GROUPS,
    PQC_ALGORITHMS,
    PQCAlgorithm,
)
from analysis.bitcoin_pqc_analysis import (
    BitcoinAnalysisResults,
    run_full_bitcoin_analysis,
)
from analysis.ethereum_pqc_analysis import (
    EthereumAnalysisResults,
    run_full_ethereum_analysis,
)
from analysis.migration_model import (
    MigrationResults,
    run_full_migration_analysis,
)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write_csv(path: str, rows: List[dict], fieldnames: Optional[List[str]] = None) -> None:
    """Write a list of dicts to CSV."""
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {path} ({len(rows)} rows)")


def _dataclass_to_dict(obj: Any) -> dict:
    """Convert a dataclass to dict, handling nested types."""
    return asdict(obj)


# ── Filter algorithms ──────────────────────────────────────────────
def _filter_algorithms(family_filter: str) -> List[PQCAlgorithm]:
    """Filter algorithms by family name."""
    if family_filter == "all":
        return ALL_ALGORITHMS
    family_filter = family_filter.lower()
    # Always include ECDSA baseline
    result = [ECDSA]
    for fam, algs in FAMILY_GROUPS.items():
        if fam == family_filter:
            result.extend(algs)
    if len(result) == 1:
        print(f"Warning: no algorithms found for family '{family_filter}', using all")
        return ALL_ALGORITHMS
    return result


# ── Bitcoin output ─────────────────────────────────────────────────
def save_bitcoin_results(results: BitcoinAnalysisResults, base_dir: str) -> None:
    _ensure_dir(base_dir)

    # Block capacity
    rows = [_dataclass_to_dict(r) for r in results.block_capacity]
    _write_csv(os.path.join(base_dir, "block_capacity.csv"), rows)

    # Policy comparison
    rows = [_dataclass_to_dict(r) for r in results.policy_comparison]
    _write_csv(os.path.join(base_dir, "witness_policy_comparison.csv"), rows)

    # Fee market
    rows = [_dataclass_to_dict(r) for r in results.fee_market]
    _write_csv(os.path.join(base_dir, "fee_market_simulation.csv"), rows)


# ── Ethereum output ────────────────────────────────────────────────
def save_ethereum_results(results: EthereumAnalysisResults, base_dir: str) -> None:
    _ensure_dir(base_dir)

    rows = [_dataclass_to_dict(r) for r in results.gas_cost]
    _write_csv(os.path.join(base_dir, "gas_cost_analysis.csv"), rows)

    rows = [_dataclass_to_dict(r) for r in results.eip1559]
    _write_csv(os.path.join(base_dir, "eip1559_dynamics.csv"), rows)

    rows = [_dataclass_to_dict(r) for r in results.consensus]
    _write_csv(os.path.join(base_dir, "consensus_layer.csv"), rows)

    rows = [_dataclass_to_dict(r) for r in results.validator_economics]
    _write_csv(os.path.join(base_dir, "validator_economics.csv"), rows)


# ── Migration output ───────────────────────────────────────────────
def save_migration_results(results: MigrationResults, base_dir: str) -> None:
    _ensure_dir(base_dir)

    # Bitcoin migration curves
    btc_rows = []
    for mr in results.bitcoin:
        for pt in mr.curve:
            d = _dataclass_to_dict(pt)
            d["critical_50pct_tps_threshold"] = mr.critical_50pct_tps_threshold
            d["fee_2x_threshold"] = mr.fee_2x_threshold
            btc_rows.append(d)
    _write_csv(os.path.join(base_dir, "bitcoin_migration.csv"), btc_rows)

    # Ethereum migration curves
    eth_rows = []
    for mr in results.ethereum:
        for pt in mr.curve:
            d = _dataclass_to_dict(pt)
            d["gas_limit_increase_threshold"] = mr.gas_limit_increase_threshold
            d["consensus_feasibility"] = mr.consensus_feasibility
            eth_rows.append(d)
    _write_csv(os.path.join(base_dir, "ethereum_migration.csv"), eth_rows)

    # Threshold summary — unified schema
    threshold_rows = []
    for mr in results.bitcoin:
        threshold_rows.append({
            "chain": "Bitcoin",
            "algorithm": mr.algorithm,
            "critical_50pct_tps_threshold": mr.critical_50pct_tps_threshold,
            "fee_2x_threshold": mr.fee_2x_threshold,
            "gas_limit_increase_threshold": "",
            "consensus_feasibility": "",
        })
    for mr in results.ethereum:
        threshold_rows.append({
            "chain": "Ethereum",
            "algorithm": mr.algorithm,
            "critical_50pct_tps_threshold": "",
            "fee_2x_threshold": "",
            "gas_limit_increase_threshold": mr.gas_limit_increase_threshold,
            "consensus_feasibility": mr.consensus_feasibility,
        })
    _write_csv(os.path.join(base_dir, "migration_thresholds.csv"), threshold_rows)


# ── Summary markdown ───────────────────────────────────────────────
def generate_summary_markdown(
    btc: Optional[BitcoinAnalysisResults],
    eth: Optional[EthereumAnalysisResults],
    mig: Optional[MigrationResults],
    out_path: str,
) -> None:
    """Generate publication-ready markdown summary tables."""
    lines = ["# PQC Impact Analysis — Summary Tables\n"]

    if btc:
        lines.append("## Bitcoin: Block Capacity Under PQC\n")
        lines.append("| Algorithm | Security | Sig (B) | PK (B) | Tx Weight | Txs/Block | TPS | Throughput Reduction |")
        lines.append("|-----------|----------|---------|--------|-----------|-----------|-----|---------------------|")
        for r in btc.block_capacity:
            lines.append(
                f"| {r.algorithm} | {r.security_level} | {r.sig_bytes:,} | {r.pk_bytes:,} "
                f"| {r.tx_weight:,.0f} | {r.txs_per_block:,} | {r.effective_tps:.2f} "
                f"| {r.throughput_reduction_pct:.1f}% |"
            )
        lines.append("")

        lines.append("## Bitcoin: Fee Market Impact (50% PQC, Medium Pressure)\n")
        lines.append("| Algorithm | Txs Included | Revenue (sat) | ECDSA Incl. | PQC Incl. | Fee Premium | PQC Stuck |")
        lines.append("|-----------|-------------|---------------|-------------|-----------|-------------|-----------|")
        for r in btc.fee_market:
            if r.mempool_pressure == "medium":
                lines.append(
                    f"| {r.algorithm} | {r.block_txs_included:,} | {r.block_fee_revenue_sat:,.0f} "
                    f"| {r.ecdsa_inclusion_rate:.1%} | {r.pqc_inclusion_rate:.1%} "
                    f"| {r.fee_premium_pct:+.1f}% | {r.pqc_txs_stuck:,} |"
                )
        lines.append("")

    if eth:
        lines.append("## Ethereum: Gas Cost Analysis\n")
        lines.append("| Algorithm | Security | Verify Gas | Overhead | Simple TPS | ERC-20 TPS | Reduction |")
        lines.append("|-----------|----------|------------|----------|------------|------------|-----------|")
        for r in eth.gas_cost:
            lines.append(
                f"| {r.algorithm} | {r.security_level} | {r.verify_gas:,} "
                f"| {r.total_overhead_gas:+,} | {r.simple_tps:.1f} | {r.erc20_tps:.1f} "
                f"| {r.throughput_reduction_simple_pct:.1f}% |"
            )
        lines.append("")

        lines.append("## Ethereum: EIP-1559 Base Fee Impact\n")
        lines.append("| Algorithm | Equilibrium Fee (gwei) | Multiplier | Avg Utilization | Blocks > Target |")
        lines.append("|-----------|------------------------|------------|-----------------|-----------------|")
        for r in eth.eip1559:
            lines.append(
                f"| {r.algorithm} | {r.equilibrium_base_fee_gwei:.2f} "
                f"| {r.base_fee_multiplier:.2f}x | {r.avg_block_utilization:.1%} "
                f"| {r.blocks_over_target}/1000 |"
            )
        lines.append("")

        lines.append("## Ethereum: Consensus Layer Impact\n")
        lines.append("| Algorithm | Attestation Size | Multiplier | BW Required (Mbps) | Feasible? | Overhead (KB) |")
        lines.append("|-----------|------------------|------------|--------------------|-----------|--------------:|")
        for r in eth.consensus:
            lines.append(
                f"| {r.algorithm} | {r.committee_attestation_bytes:,} B "
                f"| {r.attestation_multiplier:.1f}x | {r.bandwidth_required_mbps:,.1f} "
                f"| {'✓' if r.slot_timing_feasible else '✗'} | {r.beacon_block_overhead_kb:,.1f} |"
            )
        lines.append("")

    if mig:
        lines.append("## Migration Thresholds\n")
        lines.append("### Bitcoin\n")
        lines.append("| Algorithm | 50% TPS Drop At | Fee 2× Premium At |")
        lines.append("|-----------|-----------------|-------------------|")
        for r in mig.bitcoin:
            tps_t = f"{r.critical_50pct_tps_threshold:.0f}%" if r.critical_50pct_tps_threshold is not None else "N/A"
            fee_t = f"{r.fee_2x_threshold:.0f}%" if r.fee_2x_threshold is not None else "N/A"
            lines.append(f"| {r.algorithm} | {tps_t} | {fee_t} |")
        lines.append("")

        lines.append("### Ethereum\n")
        lines.append("| Algorithm | Gas Limit Increase At | Consensus Feasible? |")
        lines.append("|-----------|----------------------|---------------------|")
        for r in mig.ethereum:
            gas_t = f"{r.gas_limit_increase_threshold:.0f}%" if r.gas_limit_increase_threshold is not None else "N/A"
            lines.append(f"| {r.algorithm} | {gas_t} | {'✓' if r.consensus_feasibility else '✗'} |")
        lines.append("")

    md = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"  ✓ {out_path}")


# ── Main ───────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="PQC chain-specific impact analysis")
    parser.add_argument("--chain", choices=["btc", "eth", "all"], default="all",
                        help="Which chain(s) to analyse")
    parser.add_argument("--algorithms", default="all",
                        help="Algorithm family: all, falcon, dilithium, sphincs")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--output-dir", default="results", help="Output directory")
    args = parser.parse_args()

    algorithms = _filter_algorithms(args.algorithms)
    print(f"Analysing {len(algorithms)} algorithms: {[a.name for a in algorithms]}")

    t0 = time.time()
    btc_results = None
    eth_results = None
    mig_results = None

    if args.chain in ("btc", "all"):
        print("\n── Bitcoin analysis ──")
        btc_results = run_full_bitcoin_analysis(algorithms, seed=args.seed)
        save_bitcoin_results(btc_results, os.path.join(args.output_dir, "bitcoin"))

    if args.chain in ("eth", "all"):
        print("\n── Ethereum analysis ──")
        eth_results = run_full_ethereum_analysis(algorithms)
        save_ethereum_results(eth_results, os.path.join(args.output_dir, "ethereum"))

    if args.chain == "all":
        print("\n── Migration analysis ──")
        mig_algorithms = [a for a in algorithms if a.family not in ("ecdsa", "bls")]
        mig_results = run_full_migration_analysis(mig_algorithms, seed=args.seed)
        save_migration_results(mig_results, os.path.join(args.output_dir, "migration"))

    print("\n── Summary ──")
    generate_summary_markdown(
        btc_results, eth_results, mig_results,
        os.path.join(args.output_dir, "summary_tables.md"),
    )

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
