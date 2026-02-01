"""Benchmark harness for PQC operations.

Runs KEM and signature operations multiple times, collects timing and
memory statistics, and exports results to CSV.
"""

from __future__ import annotations

import csv
import os
import statistics
import time
import tracemalloc
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, List, Optional

from pqc_lib.kem import keygen as kem_keygen, encaps, decaps, KEM_ALGORITHMS
from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS


@dataclass
class BenchmarkResult:
    operation: str
    algorithm: str
    mean_ms: float
    stddev_ms: float
    min_ms: float
    max_ms: float
    peak_memory_kb: float
    n_runs: int
    artifact_sizes: str  # JSON-like summary of key/sig/ct sizes


def _bench_callable(
    func: Callable,
    n_runs: int = 5,
    warmup_runs: int = 1,
) -> List[float]:
    """Return a list of elapsed-ms values after warmup."""
    for _ in range(warmup_runs):
        func()

    times: List[float] = []
    for _ in range(n_runs):
        start = time.perf_counter()
        func()
        times.append((time.perf_counter() - start) * 1000)
    return times


def _peak_mem_kb(func: Callable) -> float:
    tracemalloc.start()
    func()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024


def _stats(times: List[float]) -> dict:
    return {
        "mean_ms": round(statistics.mean(times), 4),
        "stddev_ms": round(statistics.stdev(times), 4) if len(times) > 1 else 0.0,
        "min_ms": round(min(times), 4),
        "max_ms": round(max(times), 4),
    }


# ------------------------------------------------------------------
# KEM benchmarks
# ------------------------------------------------------------------

def bench_kem(algorithm: str, n_runs: int = 5) -> List[BenchmarkResult]:
    """Benchmark keygen, encaps, decaps for a KEM algorithm."""
    results: List[BenchmarkResult] = []

    # Keygen
    times = _bench_callable(lambda: kem_keygen(algorithm), n_runs)
    mem = _peak_mem_kb(lambda: kem_keygen(algorithm))
    kp = kem_keygen(algorithm)
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="keygen",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes=f"pk={len(kp.public_key)} sk={len(kp.secret_key)}",
        **st,
    ))

    # Encaps
    times = _bench_callable(lambda: encaps(algorithm, kp.public_key), n_runs)
    mem = _peak_mem_kb(lambda: encaps(algorithm, kp.public_key))
    enc = encaps(algorithm, kp.public_key)
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="encaps",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes=f"ct={len(enc.ciphertext)} ss={len(enc.shared_secret)}",
        **st,
    ))

    # Decaps
    times = _bench_callable(lambda: decaps(algorithm, kp.secret_key, enc.ciphertext), n_runs)
    mem = _peak_mem_kb(lambda: decaps(algorithm, kp.secret_key, enc.ciphertext))
    dec = decaps(algorithm, kp.secret_key, enc.ciphertext)
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="decaps",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes=f"ss={len(dec.shared_secret)}",
        **st,
    ))

    return results


# ------------------------------------------------------------------
# Signature benchmarks
# ------------------------------------------------------------------

def bench_sig(algorithm: str, n_runs: int = 5, message: bytes = b"benchmark message") -> List[BenchmarkResult]:
    """Benchmark keygen, sign, verify for a signature algorithm."""
    results: List[BenchmarkResult] = []

    # Keygen
    times = _bench_callable(lambda: sign_keygen(algorithm), n_runs)
    mem = _peak_mem_kb(lambda: sign_keygen(algorithm))
    kp = sign_keygen(algorithm)
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="keygen",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes=f"pk={len(kp.public_key)} sk={len(kp.secret_key)}",
        **st,
    ))

    # Sign
    times = _bench_callable(lambda: sign(algorithm, kp.secret_key, message, kp), n_runs)
    mem = _peak_mem_kb(lambda: sign(algorithm, kp.secret_key, message, kp))
    sig_result = sign(algorithm, kp.secret_key, message, kp)
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="sign",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes=f"sig={sig_result.signature_size}",
        **st,
    ))

    # Verify
    times = _bench_callable(
        lambda: verify(algorithm, kp.public_key, message, sig_result.signature, kp),
        n_runs,
    )
    mem = _peak_mem_kb(
        lambda: verify(algorithm, kp.public_key, message, sig_result.signature, kp)
    )
    st = _stats(times)
    results.append(BenchmarkResult(
        operation="verify",
        algorithm=algorithm,
        peak_memory_kb=round(mem, 2),
        n_runs=n_runs,
        artifact_sizes="",
        **st,
    ))

    return results


# ------------------------------------------------------------------
# Run all & export
# ------------------------------------------------------------------

def run_all(n_runs: int = 5) -> List[BenchmarkResult]:
    """Run benchmarks for all KEM and signature algorithms."""
    all_results: List[BenchmarkResult] = []
    for algo in KEM_ALGORITHMS:
        all_results.extend(bench_kem(algo, n_runs))
    for algo in SIG_ALGORITHMS:
        all_results.extend(bench_sig(algo, n_runs))
    return all_results


def export_csv(results: List[BenchmarkResult], path: Optional[str] = None) -> str:
    """Write results to CSV; returns the file path used."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "results", "benchmark_results.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    return path


if __name__ == "__main__":
    print("Running PQC benchmarks ...")
    results = run_all()
    csv_path = export_csv(results)
    print(f"Results written to {csv_path}")
    for r in results:
        print(f"  {r.algorithm:30s} {r.operation:10s} {r.mean_ms:8.3f} ms (stddev {r.stddev_ms:.3f})")
