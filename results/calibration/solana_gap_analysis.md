# Calibration Gap Analysis: Solana

## Data Sources
Sources: validators.app, solanacompass.com/validators/raw. Representative of Feb-Mar 2025 conditions.

## Validation Table

| Metric | Simulated | Observed | Gap (%) | Direction |
|--------|-----------|----------|---------|-----------|
| Skip/Stale Rate | 0.5385 | 0.0500 | +976.9% | Pessimistic |
| P90 Propagation (ms) | 653.8601 | 600.0000 | +9.0% | Pessimistic |
| Effective TPS | 1623.0000 | 3000.0000 | -45.9% | Pessimistic |
| Block Time (ms) | 400.0000 | 400.0000 | +0.0% | Matched |

## Gap Analysis

### Skip/Stale Rate
- **Gap**: +976.9% (Pessimistic)
- **Model omission**: Model may over-model contention effects
- **Impact on PQC analysis**: Model overestimates stress; real PQC impact likely **better** than simulated.

### P90 Propagation (ms)
- **Gap**: +9.0% (Pessimistic)
- **Model omission**: Possible NIC over-contention in model
- **Impact on PQC analysis**: Model overestimates stress; real PQC impact likely **better** than simulated.

### Effective TPS
- **Gap**: -45.9% (Pessimistic)
- **Model omission**: Full blocks assumed; real blocks vary in utilization
- **Impact on PQC analysis**: Model overestimates stress; real PQC impact likely **better** than simulated.

### Block Time (ms)
- **Gap**: +0.0% (Matched)
- **Model omission**: Block time is a model input, not output
- **Impact on PQC analysis**: Minimal; this parameter is well-calibrated.

## Overall Assessment

- 0 metrics are optimistic (model underestimates real-world stress)
- 3 metrics are pessimistic (model overestimates stress)
- 1 metrics are well-matched

**Net direction**: The model is primarily optimistic due to simplified 
topology and missing real-world variance. PQC threshold estimates should 
be treated as **upper bounds** (real thresholds may be lower).
