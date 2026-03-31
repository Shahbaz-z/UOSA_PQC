"""Core DES engine components.

ENGINE HIERARCHY
────────────────
Use DESEngine for propagation-only runs and calibration.
Use Phase2Engine for PQC fraction sweeps, mempool dynamics, and fee experiments.
Both are exported here for convenience; see engine.py for the full hierarchy diagram.

    from simulator.core import DESEngine, SimulationConfig          # Phase 1
    from simulator.core.phase2_engine import Phase2Engine, Phase2Config  # Phase 2/3
"""

from simulator.core.events import EventType, Event
from simulator.core.engine import DESEngine, SimulationConfig

__all__ = ["EventType", "Event", "DESEngine", "SimulationConfig"]
