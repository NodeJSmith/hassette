"""E2E tests for page navigation, sidebar, pulse dot, and theme toggle."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

DESKTOP_VIEWPORT = {"width": 1280, "height": 720}
MOBILE_VIEWPORT = {"width": 375, "height": 667}

PAGES = [
    ("/ui/", "Dashboard"),
    ("/ui/apps", "App Management"),
    ("/ui/logs", "Log Viewer"),
]


def test_root_redirects_to_dashboard(page: Page, base_url: str) -> None:
    response = page.goto(base_url + "/")
    assert response is not None
    assert "/ui/" in page.url


@pytest.mark.parametrize(("path", "heading"), PAGES, ids=[p for p, _ in PAGES])
def test_all_pages_load(page: Page, base_url: str, path: str, heading: str) -> None:
    page.goto(base_url + path)
    expect(page.locator("body")).to_contain_text(heading)


# ──────────────────────────────────────────────────────────────────────
# Sidebar nav items
# ──────────────────────────────────────────────────────────────────────

# Sidebar navigation entries: (link text via data-testid, expected URL path suffix, expected content)
SIDEBAR_LINKS = [
    ("nav-dashboard", "/ui/", "Dashboard"),
    ("nav-apps", "/ui/apps", "App Management"),
    ("nav-logs", "/ui/logs", "Log Viewer"),
]


def test_sidebar_renders_nav_items(page: Page, base_url: str) -> None:
    """All 3 nav links are present with correct testids."""
    page.goto(base_url + "/ui/")
    nav_items = page.locator(".ht-nav-item")
    expect(nav_items).to_have_count(3)
    for testid, _, _ in SIDEBAR_LINKS:
        expect(page.locator(f'[data-testid="{testid}"]')).to_be_visible()


@pytest.mark.parametrize(
    ("testid", "expected_path", "expected_content"),
    SIDEBAR_LINKS,
    ids=[t for t, _, _ in SIDEBAR_LINKS],
)
def test_sidebar_navigation(page: Page, base_url: str, testid: str, expected_path: str, expected_content: str) -> None:
    """Clicking a nav item navigates to the correct page."""
    page.goto(base_url + "/ui/")
    page.locator(f'[data-testid="{testid}"]').click()
    expect(page).to_have_url(re.compile(re.escape(expected_path)))
    expect(page.locator("body")).to_contain_text(expected_content)


# Map pages to the active nav item testid
SIDEBAR_ACTIVE = [
    ("/ui/", "nav-dashboard"),
    ("/ui/apps", "nav-apps"),
    ("/ui/logs", "nav-logs"),
]


@pytest.mark.parametrize(("path", "testid"), SIDEBAR_ACTIVE, ids=[p for p, _ in SIDEBAR_ACTIVE])
def test_sidebar_active_state(page: Page, base_url: str, path: str, testid: str) -> None:
    """Active nav item has the is-active class on each page."""
    page.goto(base_url + path)
    active_item = page.locator(f'[data-testid="{testid}"]')
    expect(active_item).to_have_class(re.compile(r"\bis-active\b"))


# ──────────────────────────────────────────────────────────────────────
# Sidebar layout
# ──────────────────────────────────────────────────────────────────────


def test_sidebar_renders_at_56px(page: Page, base_url: str) -> None:
    """Sidebar icon rail renders at 56px width."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    box = sidebar.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(56, abs=4)


def test_brand_link_navigates_to_dashboard(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/apps")
    page.locator(".ht-brand-link").click()
    expect(page).to_have_url(re.compile(r"/ui/?$"))


# ──────────────────────────────────────────────────────────────────────
# Pulse dot
# ──────────────────────────────────────────────────────────────────────


def test_pulse_dot_visible(page: Page, base_url: str) -> None:
    """Pulse dot element is visible in the sidebar."""
    page.goto(base_url + "/ui/")
    pulse_dot = page.locator('[data-testid="pulse-dot"]')
    expect(pulse_dot).to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Theme toggle
# ──────────────────────────────────────────────────────────────────────


def test_theme_toggle_switches_mode(page: Page, base_url: str) -> None:
    """Clicking the theme toggle changes the data-theme attribute."""
    page.goto(base_url + "/ui/")
    html = page.locator("html")
    # Default is dark
    expect(html).to_have_attribute("data-theme", "dark")
    # Click toggle to switch to light
    page.locator('[data-testid="theme-toggle"]').click()
    expect(html).to_have_attribute("data-theme", "light")
    # Click again to switch back to dark
    page.locator('[data-testid="theme-toggle"]').click()
    expect(html).to_have_attribute("data-theme", "dark")


def test_theme_persists_across_reload(page: Page, base_url: str) -> None:
    """Theme preference persists in localStorage across page reloads."""
    page.goto(base_url + "/ui/")
    # Switch to light mode
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    # Reload the page
    page.reload()
    # Should still be light
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    # Clean up: switch back to dark
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


# ──────────────────────────────────────────────────────────────────────
# Responsive: sidebar hidden below 768px
# ──────────────────────────────────────────────────────────────────────


def test_mobile_sidebar_hidden(page: Page, base_url: str) -> None:
    """Sidebar is hidden on mobile viewports."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).not_to_be_visible()
