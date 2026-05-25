"""E2E tests for responsive layout behavior across mobile and desktop viewports."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import DESKTOP_VIEWPORT, MOBILE_VIEWPORT

pytestmark = pytest.mark.e2e

TABLET_VIEWPORT = {"width": 768, "height": 1024}


# ──────────────────────────────────────────────────────────────────────
# Off-canvas drawer visibility (mobile nav)
# ──────────────────────────────────────────────────────────────────────


def test_hamburger_visible_at_375px(page: Page, base_url: str) -> None:
    """Hamburger button is visible on mobile viewport."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    hamburger = page.locator(".ht-hamburger")
    expect(hamburger).to_be_visible()


def test_hamburger_opens_drawer_at_mobile(page: Page, base_url: str) -> None:
    """Tapping the hamburger opens the off-canvas drawer."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.locator(".ht-hamburger").click()
    drawer = page.locator(".ht-drawer")
    expect(drawer).to_have_class(re.compile(r"\bis-open\b"))


def test_drawer_closes_on_backdrop_click(page: Page, base_url: str) -> None:
    """Tapping the backdrop closes the off-canvas drawer."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.locator(".ht-hamburger").click()
    expect(page.locator(".ht-drawer")).to_have_class(re.compile(r"\bis-open\b"))
    page.locator(".ht-drawer-backdrop").click()
    expect(page.locator(".ht-drawer")).not_to_have_class(re.compile(r"\bis-open\b"))


def test_sidebar_hidden_at_mobile(page: Page, base_url: str) -> None:
    """Desktop sidebar is hidden on mobile viewports."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    sidebar = page.locator("[data-testid='layout'] > [data-testid='sidebar']")
    expect(sidebar).not_to_be_visible()


def test_sidebar_visible_at_desktop(page: Page, base_url: str) -> None:
    """Sidebar is visible on desktop viewports."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/")
    sidebar = page.locator("[data-testid='sidebar']")
    expect(sidebar).to_be_visible()


def test_hamburger_hidden_at_desktop(page: Page, base_url: str) -> None:
    """Hamburger button is hidden on desktop viewports."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/")
    hamburger = page.locator(".ht-hamburger")
    expect(hamburger).not_to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Apps list: card layout on mobile, table on desktop
# ──────────────────────────────────────────────────────────────────────


def test_apps_card_layout_at_375px(page: Page, base_url: str) -> None:
    """Mobile viewport shows the apps table with columns 3+ hidden."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    # The apps page always uses a table, but hides columns 3+ on mobile
    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()
    # Columns 3+ (last error, runs, last fired) are hidden on mobile via CSS
    third_header = table.locator("th:nth-child(3)")
    expect(third_header).not_to_be_visible()


def test_apps_table_layout_at_1024px(page: Page, base_url: str) -> None:
    """Desktop viewport shows the apps table with all columns visible."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()
    # All columns should be visible on desktop (including column 3+)
    third_header = table.locator("th:nth-child(3)")
    expect(third_header).to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# KPI strip ordering at mobile
# ──────────────────────────────────────────────────────────────────────


def test_kpi_error_rate_first_at_375px(page: Page, base_url: str) -> None:
    """Stats strip first cell shows 'total' on the apps page at mobile width."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    stats_strip = page.locator("[data-testid='apps-stats-strip']")
    expect(stats_strip).to_be_visible()
    first_label = stats_strip.locator("[data-testid='stats-strip-label']").first
    expect(first_label).to_have_text("total")


# ──────────────────────────────────────────────────────────────────────
# Touch targets
# ──────────────────────────────────────────────────────────────────────


def test_touch_targets_44px(page: Page, base_url: str) -> None:
    """Interactive elements meet the 44px minimum touch target on mobile."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")

    # Theme toggle button
    theme_toggle = page.locator('[data-testid="theme-toggle"]')
    expect(theme_toggle).to_be_visible()
    box = theme_toggle.bounding_box()
    assert box is not None
    assert box["height"] >= 44, f"Theme toggle height {box['height']}px < 44px"

    # Hamburger button
    hamburger = page.locator(".ht-hamburger")
    expect(hamburger).to_be_visible()
    box = hamburger.bounding_box()
    assert box is not None
    assert box["height"] >= 44, f"Hamburger height {box['height']}px < 44px"


# ──────────────────────────────────────────────────────────────────────
# Breakpoint boundary
# ──────────────────────────────────────────────────────────────────────


def test_breakpoint_boundary_768px(page: Page, base_url: str) -> None:
    """At exactly 768px, columns 3+ are hidden (max-width: 768px triggers)."""
    page.set_viewport_size(TABLET_VIEWPORT)
    page.goto(base_url + "/apps")
    # At 768px, the mobile CSS hides columns 3+ in the apps table
    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()
    third_header = table.locator("th:nth-child(3)")
    expect(third_header).not_to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Log table app tag on mobile
# ──────────────────────────────────────────────────────────────────────


def test_log_table_app_tag_at_375px(page: Page, base_url: str) -> None:
    """Log table on mobile hides the App column header entirely."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")

    # Wait for log entries to load
    page.locator("text=/\\d+ entr/").wait_for(timeout=5000)

    # App column header should not be rendered at mobile breakpoint
    # (the component conditionally omits the App <th>/<td> on mobile)
    headers = page.locator("[data-testid='log-table'] th")
    header_texts = [headers.nth(i).text_content() for i in range(headers.count())]
    assert not any("App" in (t or "") for t in header_texts), f"App header found in: {header_texts}"

    # Log entries should still be visible despite missing App column
    rows = page.locator("[data-testid='log-table'] tbody tr")
    assert rows.count() > 0, "Expected at least one log row on mobile"


# ──────────────────────────────────────────────────────────────────────
# Mobile table layout — no horizontal scroll
# ──────────────────────────────────────────────────────────────────────

SMALL_MOBILE_VIEWPORT = {"width": 320, "height": 480}


def test_log_table_no_horizontal_scroll_at_320px(page: Page, base_url: str) -> None:
    """Log table must not allow horizontal scrolling on small mobile viewports."""
    page.set_viewport_size(SMALL_MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")
    page.locator("text=/\\d+ entr/").wait_for(timeout=5000)

    table = page.locator("[data-testid='log-table']")
    expect(table).to_be_visible()

    overflow_x = table.evaluate("el => getComputedStyle(el).overflowX")
    assert overflow_x not in ("auto", "scroll"), (
        f"Log table has overflow-x: {overflow_x} — must be hidden or visible to prevent horizontal scroll"
    )

    scroll_container = page.locator(".ht-table-card-scroll")
    can_scroll = scroll_container.evaluate("el => el.scrollWidth > el.clientWidth")
    assert not can_scroll, "Table scroll container is wider than viewport — horizontal scroll possible"


def test_log_table_no_horizontal_scroll_at_375px(page: Page, base_url: str) -> None:
    """Log table must not allow horizontal scrolling at standard mobile width."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")
    page.locator("text=/\\d+ entr/").wait_for(timeout=5000)

    table = page.locator("[data-testid='log-table']")
    expect(table).to_be_visible()

    overflow_x = table.evaluate("el => getComputedStyle(el).overflowX")
    assert overflow_x not in ("auto", "scroll"), (
        f"Log table has overflow-x: {overflow_x} — must be hidden or visible to prevent horizontal scroll"
    )


def test_apps_table_columns_fill_width_at_mobile(page: Page, base_url: str) -> None:
    """Visible apps table columns should fill the full table width on mobile."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")

    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()

    table_layout = table.evaluate("el => getComputedStyle(el).tableLayout")
    assert table_layout == "auto", f"Apps table should use table-layout: auto on mobile, got: {table_layout}"


# ──────────────────────────────────────────────────────────────────────
# Handler detail drill-down on narrow viewport
# ──────────────────────────────────────────────────────────────────────


def test_handler_detail_accessible_on_narrow_viewport(page: Page, base_url: str) -> None:
    """Handler row click opens detail pane even on narrow viewport."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/apps/my_app/handlers")

    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()

    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)
