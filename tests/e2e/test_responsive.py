"""E2E tests for responsive layout behavior across mobile and desktop viewports."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import (
    DATA_LOAD_TIMEOUT_MS,
    DESKTOP_VIEWPORT,
    MOBILE_BOUNDARY_VIEWPORT,
    MOBILE_VIEWPORT,
    NARROW_DESKTOP_VIEWPORT,
    SMALL_MOBILE_VIEWPORT,
)

pytestmark = pytest.mark.e2e

MIN_TOUCH_TARGET_PX = 44


def test_hamburger_visible_at_375px(page: Page, base_url: str) -> None:
    """Hamburger button is visible on mobile viewport."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    hamburger = page.locator("[data-testid='hamburger']")
    expect(hamburger).to_be_visible()


def test_hamburger_is_not_covered_on_deep_route_at_narrowest_viewport(page: Page, base_url: str) -> None:
    """Nothing in the status bar may overlap the hamburger, however tight the space.

    Regression: the status bar's left group carried ``min-width: 0``, so a wide right-hand
    group squeezed it to zero width. The hamburger then overflowed its own box and the
    connection indicator rendered on top of it, silently swallowing every tap. Playwright
    reported this as a 30s click timeout rather than anything layout-shaped, so this test
    hit-tests the button's centre point directly. The deepest route at the smallest
    supported viewport is the worst case for that squeeze.
    """
    page.set_viewport_size(SMALL_MOBILE_VIEWPORT)
    page.goto(base_url + "/apps/my_app/handlers/job/1")
    page.wait_for_selector("[data-testid='hamburger']")

    # The current layout happens to fit at this width, so squeezing has to be forced —
    # otherwise this passes whether or not the left group's minimum still holds. The
    # injected block stands in for the right group growing (more alert indicators firing,
    # a wider time selector, a longer preset label).
    topmost = page.evaluate("""() => {
        const ham = document.querySelector("[data-testid='hamburger']");
        const right = ham.parentElement.nextElementSibling;
        const hog = document.createElement('div');
        hog.style.cssText = 'width:600px;flex-shrink:0;height:10px';
        right.appendChild(hog);
        const r = ham.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        hog.remove();
        return hit ? hit.closest('[data-testid]')?.getAttribute('data-testid') : null;
    }""")

    assert topmost == "hamburger", f"something is covering the hamburger: {topmost}"


def test_hamburger_opens_drawer_at_mobile(page: Page, base_url: str) -> None:
    """Tapping the hamburger opens the off-canvas drawer."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.locator("[data-testid='hamburger']").click()
    # The mobile drawer is a hand-rolled Tailwind off-canvas panel (not the shadcn/vaul
    # Drawer used elsewhere) — open/closed state is a translate-x utility class toggle,
    # identified via data-testid rather than the pre-migration .ht-drawer CSS Module class.
    drawer = page.locator("[data-testid='mobile-drawer']")
    expect(drawer).to_have_class(re.compile(r"\btranslate-x-0\b"))


def test_drawer_closes_on_backdrop_click(page: Page, base_url: str) -> None:
    """Tapping the backdrop closes the off-canvas drawer."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.locator("[data-testid='hamburger']").click()
    drawer = page.locator("[data-testid='mobile-drawer']")
    expect(drawer).to_have_class(re.compile(r"\btranslate-x-0\b"))
    page.locator("[data-testid='mobile-drawer-backdrop']").click()
    expect(drawer).to_have_class(re.compile(r"-translate-x-full"))


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
    hamburger = page.locator("[data-testid='hamburger']")
    expect(hamburger).not_to_be_visible()


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


def test_kpi_error_rate_first_at_375px(page: Page, base_url: str) -> None:
    """Stats strip first cell shows 'total' on the apps page at mobile width."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    stats_strip = page.locator("[data-testid='apps-stats-strip']")
    expect(stats_strip).to_be_visible()
    first_label = stats_strip.locator("[data-testid='stats-strip-label']").first
    expect(first_label).to_have_text("total")


def test_touch_targets_44px(page: Page, base_url: str) -> None:
    """Interactive elements meet the 44px minimum touch target on mobile."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")

    # Theme toggle button
    theme_toggle = page.locator('[data-testid="theme-toggle"]')
    expect(theme_toggle).to_be_visible()
    box = theme_toggle.bounding_box()
    assert box is not None
    assert box["height"] >= MIN_TOUCH_TARGET_PX, f"Theme toggle height {box['height']}px < {MIN_TOUCH_TARGET_PX}px"

    # Hamburger button
    hamburger = page.locator("[data-testid='hamburger']")
    expect(hamburger).to_be_visible()
    box = hamburger.bounding_box()
    assert box is not None
    assert box["height"] >= MIN_TOUCH_TARGET_PX, f"Hamburger height {box['height']}px < {MIN_TOUCH_TARGET_PX}px"


def test_breakpoint_boundary_768px(page: Page, base_url: str) -> None:
    """At exactly 768px, columns 3+ are hidden (max-width: 768px triggers)."""
    page.set_viewport_size(MOBILE_BOUNDARY_VIEWPORT)
    page.goto(base_url + "/apps")
    # At 768px, the mobile CSS hides columns 3+ in the apps table
    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()
    third_header = table.locator("th:nth-child(3)")
    expect(third_header).not_to_be_visible()


def test_log_table_app_tag_at_375px(page: Page, base_url: str) -> None:
    """Log table on mobile hides the App column header entirely."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")

    # Wait for log entries to load
    page.locator("text=/\\d+ entr/").wait_for(timeout=DATA_LOAD_TIMEOUT_MS)

    # App column header should not be rendered at mobile breakpoint
    # (the component conditionally omits the App <th>/<td> on mobile)
    headers = page.locator("[data-testid='log-table'] th")
    header_texts = [headers.nth(i).text_content() for i in range(headers.count())]
    assert not any("App" in (t or "") for t in header_texts), f"App header found in: {header_texts}"

    # Log entries should still be visible despite missing App column
    rows = page.locator("[data-testid='log-table'] tbody tr")
    assert rows.count() > 0, "Expected at least one log row on mobile"


def test_log_table_no_horizontal_scroll_at_320px(page: Page, base_url: str) -> None:
    """Log table must not allow horizontal scrolling on small mobile viewports."""
    page.set_viewport_size(SMALL_MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")
    page.locator("text=/\\d+ entr/").wait_for(timeout=DATA_LOAD_TIMEOUT_MS)

    table = page.locator("[data-testid='log-table']")
    expect(table).to_be_visible()

    overflow_x = table.evaluate("el => getComputedStyle(el).overflowX")
    assert overflow_x not in ("auto", "scroll"), (
        f"Log table has overflow-x: {overflow_x} — must be hidden or visible to prevent horizontal scroll"
    )

    page_scrollable = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert not page_scrollable, "Page is horizontally scrollable — table content is breaking out of viewport"


def test_log_table_no_horizontal_scroll_at_375px(page: Page, base_url: str) -> None:
    """Log table must not allow horizontal scrolling at standard mobile width."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")
    page.locator("text=/\\d+ entr/").wait_for(timeout=DATA_LOAD_TIMEOUT_MS)

    table = page.locator("[data-testid='log-table']")
    expect(table).to_be_visible()

    overflow_x = table.evaluate("el => getComputedStyle(el).overflowX")
    assert overflow_x not in ("auto", "scroll"), (
        f"Log table has overflow-x: {overflow_x} — must be hidden or visible to prevent horizontal scroll"
    )


def test_apps_table_columns_fill_width_at_mobile(page: Page, base_url: str) -> None:
    """Visible apps table columns should fill the full table width on mobile.

    The table keeps table-layout: fixed on mobile (auto layout lets long mono
    names push the table past the viewport); the colgroup reallocates all
    width to the two visible columns.
    """
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")

    table = page.locator("[data-testid='apps-table']")
    expect(table).to_be_visible()

    table_layout = table.evaluate("el => getComputedStyle(el).tableLayout")
    assert table_layout == "fixed", f"Apps table should use table-layout: fixed on mobile, got: {table_layout}"

    page_scrollable = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert not page_scrollable, "Page is horizontally scrollable — apps table is breaking out of viewport"


def test_handler_detail_accessible_on_narrow_viewport(page: Page, base_url: str) -> None:
    """Handler row click opens detail pane even on narrow viewport."""
    page.set_viewport_size(NARROW_DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps/my_app/handlers")

    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()

    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=DATA_LOAD_TIMEOUT_MS)
