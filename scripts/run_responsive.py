"""Run a report stage with bounded numerical threads and low Windows priority."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import runpy
import sys


def lower_priority():
    if os.name=="nt":
        # Explicit pointer width matters for the pseudo-handle on 64-bit Windows.
        if not ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(-1),0x4000):raise ctypes.WinError()


def main():
    if len(sys.argv)<2:raise SystemExit("Usage: python scripts/run_responsive.py <stage.py> [stage arguments]")
    os.environ["OPENBLAS_NUM_THREADS"]="1"
    os.environ["OMP_NUM_THREADS"]="1"
    lower_priority()
    stage=Path(sys.argv[1]).resolve()
    if not stage.is_file():raise FileNotFoundError(stage)
    sys.argv=sys.argv[1:];sys.path.insert(0,str(stage.parent))
    runpy.run_path(str(stage),run_name="__main__")


if __name__=="__main__":main()
