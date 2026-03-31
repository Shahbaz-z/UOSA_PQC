"""PQC Network Simulator — Discrete Event Simulation for blockchain propagation.

ENGINE HIERARCHY (quick reference)
────────────────────────────────────
  DESEngine        — Phase 1: propagation, calibration, new module integration
  Phase2Engine     — Phase 2/3: PQC sweeps, mempool, fee market, vote overhead
  See simulator/core/engine.py for the full hierarchy diagram.

USAGE
─────
  # Phase 1 — propagation only
  from simulator import DESEngine, SimulationConfig
  result = DESEngine(SimulationConfig(chain="solana", ...)).run()

  # Phase 2/3 — PQC sweeps with stochastic arrivals and fee market
  from simulator.core.phase2_engine import Phase2Engine, Phase2Config
  result = Phase2Engine(Phase2Config(chain="solana", pqc_fraction=0.5)).run()
"""

from simulator.core.engine import DESEngine, SimulationConfig
from simulator.results import SimulationResult, ComparisonResult
from simulator.calibration.runner import run_calibration, CalibrationResult

__all__ = [
    "DESEngine",
    "SimulationConfig",
    "SimulationResult",
    "ComparisonResult",
    "run_calibration",
    "CalibrationResult",
]
