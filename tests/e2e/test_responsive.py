"""E2E tests for responsive layout behavior across mobile and desktop viewports."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import DESKTOP_VIEWPORT, MOBILE_VIEWPORT

pytestmark = pytest.mark.e2e

TABLET_VIEWPORT = {"width": 768, "height": 1024}


# ──────────────────────────────────────────────────────────────────────
# Bottom nav visibility
# ──────────────────────────────────────────────────────────────────────


def test_bottom_nav_visible_at_375px(page: Page, base_url: str) -> None:
    """Bottom navigation bar is visible on mobile with 4 items."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    nav = page.locator(".ht-bottom-nav")
    expect(nav).to_be_visible()
    items = nav.locator(".ht-bottom-nav__item")
    expect(items).to_have_count(4)


def test_bottom_nav_hidden_at_1024px(page: Page, base_url: str) -> None:
    """Bottom navigation bar is hidden on desktop viewports."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/")
    nav = page.locator(".ht-bottom-nav")
    expect(nav).not_to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Bottom nav navigation
# ──────────────────────────────────────────────────────────────────────

BOTTOM_NAV_TABS = [
    ("nav-dashboard-mobile", "/"),
    ("nav-apps-mobile", "/apps"),
    ("nav-logs-mobile", "/logs"),
    ("nav-sessions-mobile", "/sessions"),
]


@pytest.mark.parametrize(
    ("testid", "expected_path"),
    BOTTOM_NAV_TABS,
    ids=[t for t, _ in BOTTOM_NAV_TABS],
)
def test_bottom_nav_navigation(page: Page, base_url: str, testid: str, expected_path: str) -> None:
    """Clicking bottom nav tabs navigates to the correct page."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.locator(f'[data-testid="{testid}"]').click()
    if expected_path == "/":
        expect(page).to_have_url(base_url + "/")
    else:
        expect(page).to_have_url(re.compile(re.escape(expected_path.rstrip("/")) + r"/?$"))


# ──────────────────────────────────────────────────────────────────────
# Apps list: card layout on mobile, table on desktop
# ──────────────────────────────────────────────────────────────────────


def test_apps_card_layout_at_375px(page: Page, base_url: str) -> None:
    """Mobile viewport shows app cards, not the dense table."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    cards = page.locator(".ht-manifest-card")
    expect(cards.first).to_be_visible()
    dense_table = page.locator("table.ht-table--dense")
    expect(dense_table).to_have_count(0)


def test_apps_table_layout_at_1024px(page: Page, base_url: str) -> None:
    """Desktop viewport shows the dense table, not cards."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    dense_table = page.locator("table.ht-table--dense")
    expect(dense_table).to_be_visible()
    cards = page.locator(".ht-manifest-card")
    expect(cards).to_have_count(0)


# ──────────────────────────────────────────────────────────────────────
# KPI strip ordering at mobile
# ──────────────────────────────────────────────────────────────────────


def test_kpi_error_rate_first_at_375px(page: Page, base_url: str) -> None:
    """Error Rate KPI card is the first in the strip on mobile (spans full width)."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    kpi_strip = page.locator('[data-testid="kpi-strip"]')
    first_label = kpi_strip.locator(".ht-health-card__label").first
    expect(first_label).to_have_text("Error Rate")


# ──────────────────────────────────────────────────────────────────────
# Touch targets
# ──────────────────────────────────────────────────────────────────────


def test_touch_targets_44px(page: Page, base_url: str) -> None:
    """Interactive elements meet the 44px minimum touch target on mobile."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")

    # Scope toggle buttons
    scope_toggle = page.locator('[data-testid="scope-toggle"] button').first
    expect(scope_toggle).to_be_visible()
    box = scope_toggle.bounding_box()
    assert box is not None
    assert box["height"] >= 44, f"Scope toggle height {box['height']}px < 44px"

    # Theme toggle button
    theme_toggle = page.locator('[data-testid="theme-toggle"]')
    expect(theme_toggle).to_be_visible()
    box = theme_toggle.bounding_box()
    assert box is not None
    assert box["height"] >= 44, f"Theme toggle height {box['height']}px < 44px"

    # Bottom nav items
    nav_items = page.locator(".ht-bottom-nav__item")
    for i in range(nav_items.count()):
        box = nav_items.nth(i).bounding_box()
        assert box is not None
        assert box["height"] >= 44, f"Bottom nav item {i} height {box['height']}px < 44px"


# ──────────────────────────────────────────────────────────────────────
# Bottom nav does not overlap content
# ──────────────────────────────────────────────────────────────────────


def test_bottom_nav_no_content_overlap(page: Page, base_url: str) -> None:
    """Content does not visually overlap with the fixed bottom nav."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/")
    page.wait_for_timeout(500)

    # Scroll the window to the bottom — .ht-main uses min-height (not height),
    # so it grows to fit content and the actual scroll container is the viewport.
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(300)

    # Use getBoundingClientRect for both elements so coordinates are in the same
    # viewport-relative system (bounding_box uses document coordinates which
    # differ from viewport coordinates after scrolling).
    overlap = page.evaluate("""
        () => {
            const main = document.querySelector('.ht-main');
            if (!main || !main.lastElementChild) return null;
            const nav = document.querySelector('.ht-bottom-nav');
            if (!nav) return null;
            const contentBottom = main.lastElementChild.getBoundingClientRect().bottom;
            const navTop = nav.getBoundingClientRect().top;
            return { contentBottom, navTop };
        }
    """)
    assert overlap is not None, "Could not find .ht-main content or .ht-bottom-nav"
    assert overlap["contentBottom"] <= overlap["navTop"] + 1, (
        f"Last content element bottom ({overlap['contentBottom']}px) overlaps bottom nav top ({overlap['navTop']}px)"
    )


# ──────────────────────────────────────────────────────────────────────
# Breakpoint boundary
# ──────────────────────────────────────────────────────────────────────


def test_breakpoint_boundary_768px(page: Page, base_url: str) -> None:
    """At exactly 768px, the card layout shows (768 triggers max-width: 768px)."""
    page.set_viewport_size(TABLET_VIEWPORT)
    page.goto(base_url + "/apps")
    # At 768px, the mobile card layout should be active (max-width: 768px matches)
    cards = page.locator(".ht-manifest-card")
    expect(cards.first).to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Log table app tag on mobile
# ──────────────────────────────────────────────────────────────────────


def test_log_table_app_tag_at_375px(page: Page, base_url: str) -> None:
    """Log table on mobile shows app name as tag in message column, no App column header."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/logs")

    # App column header should not be visible
    headers = page.locator(".ht-table-log th")
    header_texts = [headers.nth(i).text_content() for i in range(headers.count())]
    assert not any("App" in (t or "") for t in header_texts), f"App header found in: {header_texts}"

    # App name should appear as a tag inside the message column
    app_tags = page.locator(".ht-log-app-tag")
    assert app_tags.count() > 0, "Expected at least one .ht-log-app-tag element"
    expect(app_tags.first).to_be_visible()
    expect(app_tags.first).to_have_class(re.compile(r"ht-tag"))
