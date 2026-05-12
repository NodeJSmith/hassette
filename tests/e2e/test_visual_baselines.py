"""Visual baseline screenshot tests for CSS Modules Migration (T02).

These tests establish Playwright screenshot baselines at 4 viewports x 2 themes
for key pages and app-detail tabs before any component CSS migration begins.

Baselines must be generated on Ubuntu (the CI platform) to avoid OS rendering
divergence. If running locally on a non-Ubuntu OS, re-generate in CI with:

    pytest tests/e2e/test_visual_baselines.py --update-snapshots

Generated snapshot PNGs are committed in tests/e2e/test_visual_baselines-snapshots/
and tracked via the !tests/e2e/**-snapshots/*.png .gitignore exception added in T01.

Usage
-----
Generate / regenerate all baselines (first run or after intentional visual change):

    pytest tests/e2e/test_visual_baselines.py --update-snapshots -n 2

Compare against existing baselines (CI / normal test runs):

    pytest tests/e2e/test_visual_baselines.py -n 2
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

SNAPSHOT_DIR = Path(__file__).parent / "test_visual_baselines-snapshots"

# All viewports use 900px height for consistent crop. This intentionally differs
# from conftest.MOBILE_VIEWPORT (375x812) — baseline tests use uniform height
# across all viewport widths for comparable full-page screenshots, whereas
# functional tests use device-realistic dimensions.
VIEWPORTS = [
    {"width": 1440, "height": 900},
    {"width": 900, "height": 900},
    {"width": 768, "height": 900},
    {"width": 375, "height": 900},
]

THEMES = ["light", "dark"]


def _viewport_label(viewport: dict[str, int]) -> str:
    return f"{viewport['width']}w"


def _snapshot_name(page_slug: str, viewport: dict[str, int], theme: str) -> str:
    return f"{page_slug}-{_viewport_label(viewport)}-{theme}.png"


def _wait_for_page_ready(page: Page) -> None:
    """Wait for initial render to settle before taking screenshot."""
    page.wait_for_load_state("networkidle", timeout=10000)


def _navigate_with_theme(page: Page, url: str, theme: str) -> None:
    """Seed theme in localStorage before navigating so the page renders with the correct theme from first paint."""
    page.evaluate(f"localStorage.setItem('hassette:theme', JSON.stringify('{theme}'));")
    page.goto(url)
    _wait_for_page_ready(page)
    page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}');")


SIZE_TOLERANCE = 0.05


def _take_and_assert(
    request: pytest.FixtureRequest,
    page: Page,
    name: str,
) -> None:
    """Take a screenshot and either save it as a baseline or compare to existing.

    When --update-snapshots is passed: write the PNG to the snapshot dir.
    Otherwise: compare screenshot file size against baseline within a 5% tolerance.

    Limitation: file-size comparison catches large regressions (blank pages, fully
    collapsed sections) but cannot detect subtle layout shifts where overall byte
    count stays similar. A pixel-diff approach (e.g. Pillow ImageChops) would be
    more reliable but requires masking dynamic content (timestamps, durations).
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    reference_path = SNAPSHOT_DIR / name

    update = request.config.getoption("--update-snapshots", default=False)

    if update:
        page.screenshot(path=str(reference_path), full_page=True)
        return

    if not reference_path.exists():
        page.screenshot(path=str(reference_path), full_page=True)
        pytest.skip(f"Baseline not yet established — saved to {reference_path.name}. Commit and re-run.")

    actual_bytes = page.screenshot(full_page=True)
    ref_size = reference_path.stat().st_size
    actual_size = len(actual_bytes)
    size_ratio = abs(actual_size - ref_size) / max(ref_size, 1)

    if size_ratio > SIZE_TOLERANCE:
        actual_path = SNAPSHOT_DIR / name.replace(".png", "-actual.png")
        actual_path.write_bytes(actual_bytes)
        pytest.fail(
            f"Visual regression detected for {name}: "
            f"screenshot size changed by {size_ratio:.1%} (threshold {SIZE_TOLERANCE:.0%}). "
            f"Reference={ref_size} bytes, actual={actual_size} bytes. "
            f"Actual saved to {actual_path.name}. "
            "Run with --update-snapshots if this change is intentional."
        )


# ──────────────────────────────────────────────────────────────────────
# Apps list page
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_apps_list_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the apps list page at each viewport and theme."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps", theme)
    _take_and_assert(request, page, _snapshot_name("apps-list", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# Handlers page
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_handlers_page_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the handlers page at each viewport and theme."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/handlers", theme)
    _take_and_assert(request, page, _snapshot_name("handlers", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# Logs page
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_logs_page_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the logs page at each viewport and theme."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/logs", theme)
    _take_and_assert(request, page, _snapshot_name("logs", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# Diagnostics page
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_diagnostics_page_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the diagnostics page."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/diagnostics", theme)
    _take_and_assert(request, page, _snapshot_name("diagnostics", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# Config page
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_config_page_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the config page at each viewport and theme."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/config", theme)
    _take_and_assert(request, page, _snapshot_name("config", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# App-detail tabs: overview, handlers, code, config
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_app_detail_overview_tab_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the app-detail overview tab."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps/my_app/overview", theme)
    _take_and_assert(request, page, _snapshot_name("app-detail-overview", viewport, theme))


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_app_detail_handlers_tab_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the app-detail handlers tab."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps/my_app/handlers", theme)
    _take_and_assert(request, page, _snapshot_name("app-detail-handlers", viewport, theme))


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_app_detail_code_tab_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the app-detail code tab."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps/my_app/code", theme)
    _take_and_assert(request, page, _snapshot_name("app-detail-code", viewport, theme))


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_app_detail_config_tab_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the app-detail config tab."""
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps/my_app/config", theme)
    _take_and_assert(request, page, _snapshot_name("app-detail-config", viewport, theme))


# ──────────────────────────────────────────────────────────────────────
# Mobile sidebar (drawer open at ≤900px)
# ──────────────────────────────────────────────────────────────────────


MOBILE_VIEWPORTS = [v for v in VIEWPORTS if v["width"] <= 900]


@pytest.mark.parametrize("viewport", MOBILE_VIEWPORTS, ids=_viewport_label)
@pytest.mark.parametrize("theme", THEMES)
def test_mobile_sidebar_drawer_open_baseline(
    request: pytest.FixtureRequest,
    page: Page,
    base_url: str,
    viewport: dict[str, int],
    theme: str,
) -> None:
    """Screenshot baseline for the mobile sidebar drawer in open state.

    At viewports ≤900px the hamburger menu is shown and the sidebar is
    hidden behind an off-canvas drawer. This baseline captures the drawer
    open state.
    """
    page.set_viewport_size(viewport)
    _navigate_with_theme(page, base_url + "/apps", theme)
    hamburger = page.locator(".ht-hamburger")
    expect(hamburger).to_be_visible()
    hamburger.click()
    page.locator(".ht-drawer.is-open").wait_for(timeout=3000)
    page.wait_for_timeout(150)  # drawer slide-in transition
    _take_and_assert(request, page, _snapshot_name("mobile-sidebar-open", viewport, theme))
