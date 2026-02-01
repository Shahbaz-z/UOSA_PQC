"""Timing and memory-profiling utilities."""

import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Callable, Any, Tuple


@dataclass
class TimingResult:
    """Result of a single timed operation."""
    elapsed_ms: float
    peak_memory_kb: float
    result: Any = field(repr=False)


def timed_call(func: Callable, *args: Any, **kwargs: Any) -> TimingResult:
    """Execute *func* and return timing + peak memory delta.

    Uses ``tracemalloc`` to measure Python-heap allocations (more
    accurate for small operations than RSS-based measurement).
    """
    tracemalloc.start()
    start = time.perf_counter()

    result = func(*args, **kwargs)

    elapsed = (time.perf_counter() - start) * 1000  # ms
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return TimingResult(
        elapsed_ms=elapsed,
        peak_memory_kb=peak / 1024,
        result=result,
    )
