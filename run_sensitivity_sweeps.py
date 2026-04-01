#!/usr/bin/env python3
"""Root-level shim — delegates to scripts/run_sensitivity_sweeps.py.

All logic lives in scripts/run_sensitivity_sweeps.py.  This file exists so that
  python run_sensitivity_sweeps.py [args]
works from the repository root, matching the documented usage in README.md.
"""
import runpy, sys, os
sys.argv[0] = os.path.join(os.path.dirname(__file__), "scripts", "run_sensitivity_sweeps.py")
runpy.run_path(sys.argv[0], run_name="__main__")
