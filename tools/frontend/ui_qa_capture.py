#!/usr/bin/env python3
"""Capture the UI QA screenshot matrix against a running demo stack.

Usage:
    uv run python tools/ui_qa_capture.py --base-url http://localhost:PORT --output-dir /tmp/ui-qa

Captures every page at every viewport in both themes by default. Filter with
--pages/--viewports/--themes. Output files are named {page}--{width}--{theme}.png.

Requires the demo stack (scripts/hassette_demo.py) to be running; pass its
DEMO_FRONTEND_URL as --base-url. Playwright Chromium must be installed
(uv run playwright install chromium).
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES: dict[str, str] = {
    "apps": "/apps",
    "handlers": "/handlers",
    "logs": "/logs",
    "config": "/config",
    "diagnostics": "/diagnostics",
    "app-detail": "/apps/demo_stimulator",
    "app-handlers": "/apps/demo_stimulator/handlers",
}

VIEWPORTS: dict[str, tuple[int, int]] = {
    "320": (320, 480),
    "375": (375, 812),
    "768": (768, 1024),
    "900": (900, 700),
    "1280": (1280, 800),
}

THEMES = ("light", "dark")

SETTLE_MS = 1500

ANIMATION_KILL_CSS = (
    "const s = document.createElement('style');"
    "s.textContent = '*,*::before,*::after{animation-duration:0s!important;"
    "transition-duration:0s!important;}';"
    "document.head.appendChild(s);"
)


def capture_matrix(base_url: str, output_dir: Path, pages: list[str], viewports: list[str], themes: list[str]) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in themes:
            for vp_name in viewports:
                width, height = VIEWPORTS[vp_name]
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(f"localStorage.setItem('hassette:theme', '\"{theme}\"');")
                page = context.new_page()
                for page_name in pages:
                    page.goto(base_url + PAGES[page_name], wait_until="networkidle")
                    page.evaluate(ANIMATION_KILL_CSS)
                    page.wait_for_timeout(SETTLE_MS)
                    out = output_dir / f"{page_name}--{vp_name}--{theme}.png"
                    page.screenshot(path=str(out), full_page=True)
                    print(f"captured {out}")
                    count += 1
                context.close()
        browser.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Frontend URL from the demo stack (DEMO_FRONTEND_URL)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pages", nargs="*", choices=sorted(PAGES), default=sorted(PAGES))
    parser.add_argument("--viewports", nargs="*", choices=sorted(VIEWPORTS), default=sorted(VIEWPORTS))
    parser.add_argument("--themes", nargs="*", choices=THEMES, default=list(THEMES))
    args = parser.parse_args()

    count = capture_matrix(args.base_url, args.output_dir, args.pages, args.viewports, args.themes)
    print(f"done: {count} screenshots in {args.output_dir}")
    sys.exit(0 if count else 1)


if __name__ == "__main__":
    main()
