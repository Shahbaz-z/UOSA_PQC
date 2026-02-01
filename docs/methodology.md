# Benchmark Methodology

## Timing
- Uses `time.perf_counter()` for high-resolution monotonic timing
- Each operation run N times (default: 5) after 1 warmup run
- Reports mean, stddev, min, max in milliseconds

## Memory
- Uses `tracemalloc` to measure Python heap allocations
- Reports peak allocation per operation in KB
- **Limitation**: Does not capture C-level allocations inside liboqs;
  numbers reflect Python-side overhead only

## Block-Space Model
- Models signature contribution to Solana transaction size
- Base transaction overhead (accounts, instructions, blockhash) approximated
  as 250 bytes — a midpoint of typical simple transfers
- Block size set to 6 MB (practical limit; theoretical max is 32 MB)
- Slot time assumed 400 ms
- Does **not** model: vote transactions, priority fees, compute unit limits,
  or network propagation effects
