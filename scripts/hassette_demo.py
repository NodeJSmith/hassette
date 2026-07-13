#!/usr/bin/env python3
"""Demo orchestrator: starts HA + hassette + Vite for visual QA.

Usage:
    uv run python scripts/hassette_demo.py

Starts all services via Docker Compose, prints URLs when ready, and blocks
until signaled. On SIGINT or SIGTERM, tears down via docker compose down.

Requires Docker. Ports default to 18123 (HA), 18126 (hassette), 15173 (vite)
and are overridable via DEMO_HA_PORT, DEMO_HASSETTE_PORT, DEMO_VITE_PORT.
"""

import signal

from demo_stack import DemoStack


def main() -> None:
    with DemoStack() as demo:
        print(f"HA:       http://localhost:{demo.ha_port}", flush=True)
        print(f"Hassette: http://localhost:{demo.hassette_port}", flush=True)
        print(f"Frontend: http://localhost:{demo.vite_port}", flush=True)
        print("Demo ready.", flush=True)
        signal.pause()


if __name__ == "__main__":
    main()
