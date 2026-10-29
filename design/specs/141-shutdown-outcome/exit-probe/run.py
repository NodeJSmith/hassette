# ruff: noqa
# Throwaway probe kept verbatim as the evidence spec 141 D3 cites; not maintained code.
"""Run every design x scenario x Python as a subprocess and tabulate the outcome."""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PYS = {"3.11": sys.argv[1], "3.14": sys.argv[2]}
DESIGNS = ["base", "L", "W"]
SCENARIOS = [
    "clean",
    "idle_anyio",
    "idle_stdlib_pool",
    "stuck_user_thread",
    "error_stuck_thread",
    "hung_atexit",
    "stuck_default_executor",
    "swallowing_task",
    "frozen_loop",
]
HANG = 8.0

print(f"{'scenario':24} {'py':5} " + "  ".join(f"{d:28}" for d in DESIGNS))
for s in SCENARIOS:
    for pyv, py in PYS.items():
        cells = []
        for d in DESIGNS:
            mark = tempfile.mkdtemp()
            t0 = time.monotonic()
            p = subprocess.Popen([py, "-I", os.path.join(HERE, "child.py"), d, s, mark], stderr=subprocess.PIPE)
            try:
                _, err = p.communicate(timeout=HANG)
                rc = str(p.returncode)
            except subprocess.TimeoutExpired:
                p.kill()
                _, err = p.communicate()
                rc = "HUNG"
            dt = time.monotonic() - t0
            m = set(os.listdir(mark))
            flags = ("A" if "user_atexit_ran" in m else "-") + ("S" if "survivor_logged" in m else "-")
            cells.append(f"rc={rc:4} {dt:4.1f}s atexit/surv={flags}")
            errtxt = err.decode().strip().splitlines()
            if errtxt and os.environ.get("VERBOSE"):
                print("   ", d, s, pyv, "|", " / ".join(errtxt[-3:])[:300])
        print(f"{s:24} {pyv:5} " + "  ".join(f"{c:28}" for c in cells))
