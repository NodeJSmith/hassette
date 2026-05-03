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
    sidebar = page.locator(".ht-layout > .ht-sidebar")
    expect(sidebar).not_to_be_visible()


def test_sidebar_visible_at_desktop(page: Page, base_url: str) -> None:
    """Sidebar is visible on desktop viewports."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/")
    sidebar = page.locator(".ht-sidebar")
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

    # Wait for log entries to load
    page.locator("text=/\\d+ entr/").wait_for(timeout=5000)

    # App column header should not be visible at mobile breakpoint
    headers = page.locator(".ht-table-log th")
    header_texts = [headers.nth(i).text_content() for i in range(headers.count())]
    assert not any("App" in (t or "") for t in header_texts), f"App header found in: {header_texts}"

    # App name should appear as a tag inside the message column
    app_tags = page.locator(".ht-log-app-tag")
    assert app_tags.count() > 0, "Expected at least one .ht-log-app-tag element"
    expect(app_tags.first).to_be_visible()
    expect(app_tags.first).to_have_class(re.compile(r"ht-tag"))


# ──────────────────────────────────────────────────────────────────────
# Handler detail drill-down on narrow viewport
# ──────────────────────────────────────────────────────────────────────


def test_handler_detail_accessible_on_narrow_viewport(page: Page, base_url: str) -> None:
    """Handler row click opens detail pane even on narrow viewport."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/apps/my_app")

    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()

    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)
