"""PQC Network Simulator - Discrete Event Simulation for blockchain propagation.

Phase 1: Network Calibration Layer
- Models block propagation across realistic validator networks
- Calibrates against current Ed25519/ECDSA baseline metrics
- Provides foundation for Phase 2 (PQC injection) and Phase 3 (economic ABM)
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
