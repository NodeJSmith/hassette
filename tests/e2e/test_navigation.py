"""E2E tests for page navigation, sidebar, and theme toggle in the new Ink UI."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ANIMATION_SETTLE_MS, DESKTOP_VIEWPORT, MOBILE_VIEWPORT

pytestmark = pytest.mark.e2e

# Nav items in the new sidebar: Apps, Logs, Config (overview removed)
PAGES = [
    ("/apps", "apps", "apps"),
    ("/logs", None, None),
    ("/config", "config", "config"),
]


def test_root_redirects_to_apps(page: Page, base_url: str) -> None:
    """/ redirects to /apps."""
    page.goto(base_url + "/")
    page.wait_for_load_state("networkidle")
    expect(page).to_have_url(re.compile(r"/apps"))


def test_logs_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url + "/logs")
    expect(page.locator("[data-testid='log-table']")).to_be_visible()


def test_config_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url + "/config")
    expect(page.locator("body")).to_contain_text("config")


# ──────────────────────────────────────────────────────────────────────
# Sidebar nav items
# ──────────────────────────────────────────────────────────────────────

# Sidebar nav links: Apps, Logs, Config (overview removed in T01)
SIDEBAR_LINKS = [
    ("nav-apps", "/apps", "apps"),
    ("nav-logs", "/logs", "logs"),
    ("nav-config", "/config", "config"),
]


def test_sidebar_renders_nav_items(page: Page, base_url: str) -> None:
    """All top-level nav links are present with correct testids."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    for testid, _, _ in SIDEBAR_LINKS:
        expect(page.locator(f'[data-testid="{testid}"]')).to_be_visible()


@pytest.mark.parametrize(
    ("testid", "expected_path", "expected_content"),
    SIDEBAR_LINKS,
    ids=[t for t, _, _ in SIDEBAR_LINKS],
)
def test_sidebar_navigation(page: Page, base_url: str, testid: str, expected_path: str, expected_content: str) -> None:
    """Clicking a nav item navigates to the correct page."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    page.locator(f'[data-testid="{testid}"]').click()
    expect(page).to_have_url(re.compile(re.escape(expected_path)))
    expect(page.locator("body")).to_contain_text(expected_content)


# Map pages to the active nav item testid
SIDEBAR_ACTIVE = [
    ("/apps", "nav-apps"),
    ("/logs", "nav-logs"),
    ("/config", "nav-config"),
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


def test_sidebar_visible_on_desktop(page: Page, base_url: str) -> None:
    """Sidebar renders on desktop viewport."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    sidebar = page.locator("[data-testid='sidebar']")
    expect(sidebar).to_be_visible()


def test_brand_link_navigates_to_apps(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/logs")
    page.locator("[aria-label='Hassette home']").click()
    expect(page).to_have_url(re.compile(r"/apps"))


# ──────────────────────────────────────────────────────────────────────
# Responsive: sidebar hidden below 768px, off-canvas drawer on mobile
# ──────────────────────────────────────────────────────────────────────


def test_mobile_sidebar_hidden(page: Page, base_url: str) -> None:
    """Desktop sidebar is hidden on mobile viewports."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    sidebar = page.locator("[data-testid='layout'] > [data-testid='sidebar']")
    expect(sidebar).not_to_be_visible()


def test_mobile_hamburger_opens_drawer(page: Page, base_url: str) -> None:
    """Hamburger button is visible on mobile and opens the off-canvas drawer."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    hamburger = page.locator("[data-testid='hamburger']")
    expect(hamburger).to_be_visible()
    hamburger.click()
    drawer = page.locator(".ht-drawer")
    expect(drawer).to_have_class(re.compile(r"\bis-open\b"))


def test_mobile_drawer_closes_on_backdrop_click(page: Page, base_url: str) -> None:
    """Off-canvas drawer closes when backdrop is clicked."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    page.locator("[data-testid='hamburger']").click()
    # Drawer is open
    expect(page.locator(".ht-drawer")).to_have_class(re.compile(r"\bis-open\b"))
    # Click backdrop to close
    page.locator(".ht-drawer-backdrop").click()
    expect(page.locator(".ht-drawer")).not_to_have_class(re.compile(r"\bis-open\b"))


def test_mobile_drawer_closes_on_navigation(page: Page, base_url: str) -> None:
    """Drawer closes automatically when the user navigates to a new page."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/apps")
    page.locator("[data-testid='hamburger']").click()
    expect(page.locator(".ht-drawer")).to_have_class(re.compile(r"\bis-open\b"))
    # Click a navigation link in the drawer
    page.locator(".ht-drawer [data-testid='nav-logs']").click()
    expect(page).to_have_url(re.compile(r"/logs"))
    expect(page.locator(".ht-drawer")).not_to_have_class(re.compile(r"\bis-open\b"))


# ──────────────────────────────────────────────────────────────────────
# Accessibility: skip-nav, page titles, aria-hidden icons
# ──────────────────────────────────────────────────────────────────────


def test_skip_nav_link_exists(page: Page, base_url: str) -> None:
    """Skip-nav link is first focusable element and targets #main-content."""
    page.goto(base_url + "/apps")
    skip_link = page.locator("a.ht-skip-link")
    expect(skip_link).to_have_attribute("href", "#main-content")
    main = page.locator("main#main-content")
    expect(main).to_be_attached()


TITLE_MAP = [
    ("/apps", "Apps - Hassette"),
    ("/logs", "Logs - Hassette"),
    ("/config", "Config - Hassette"),
]


@pytest.mark.parametrize(
    ("path", "expected_title"),
    TITLE_MAP,
    ids=[p for p, _ in TITLE_MAP],
)
def test_page_title_updates_per_route(
    page: Page,
    base_url: str,
    path: str,
    expected_title: str,
) -> None:
    """Each page sets a distinct document.title."""
    page.goto(base_url + path)
    expect(page).to_have_title(expected_title)


def test_sidebar_icons_are_aria_hidden(page: Page, base_url: str) -> None:
    """Decorative SVG icons in sidebar nav have aria-hidden."""
    page.goto(base_url + "/apps")
    nav_svgs = page.locator("nav[aria-label='Main navigation'] svg")
    for i in range(nav_svgs.count()):
        expect(nav_svgs.nth(i)).to_have_attribute("aria-hidden", "true")


# ──────────────────────────────────────────────────────────────────────
# App list in sidebar
# ──────────────────────────────────────────────────────────────────────


def test_sidebar_app_list_renders(page: Page, base_url: str) -> None:
    """Sidebar renders the app list with app names from seed data."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # Apps are grouped by status in the sidebar app-nav section.
    # FAILING group (broken_app) is open by default.
    app_nav = page.locator("[data-testid='app-nav']")
    expect(app_nav).to_be_visible()
    expect(app_nav).to_contain_text("Broken App")
    # RUNNING group is collapsed by default when other groups exist;
    # open it, then verify My App appears.
    running_header = page.locator("[data-testid='group-header']", has_text="RUNNING")
    expect(running_header).to_be_visible()
    running_header.click()
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    expect(app_nav).to_contain_text("My App")


def test_sidebar_app_search_filters(page: Page, base_url: str) -> None:
    """Typing in the sidebar search box filters the app list."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    search = page.locator("input[aria-label='Filter apps']")
    expect(search).to_be_visible()
    search.fill("My App")
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    # Only My App should be visible in the app nav section
    app_nav = page.locator("[data-testid='app-nav']")
    expect(app_nav).to_contain_text("My App")
    expect(app_nav).not_to_contain_text("Broken App")


def test_sidebar_clicking_app_navigates(page: Page, base_url: str) -> None:
    """Clicking an app in the sidebar navigates to its detail page."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # my_app is in the RUNNING group which is collapsed — open it first
    page.locator("[data-testid='group-header']", has_text="RUNNING").click()
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    # Click the app link in the sidebar
    page.locator("[data-testid='app-link']", has_text="My App").click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))


def test_sidebar_multi_instance_expand(page: Page, base_url: str) -> None:
    """Multi-instance apps show an expand button in the sidebar."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # multi_app is RUNNING; the RUNNING group starts collapsed when other
    # status groups have apps. Open the RUNNING group first.
    running_header = page.locator("[data-testid='group-header']", has_text="RUNNING")
    expect(running_header).to_be_visible()
    running_header.click()
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    # multi_app has 3 instances — expand button should be visible
    expand_btn = page.get_by_label("Expand Multi App", exact=False)
    expect(expand_btn).to_be_visible()
    expand_btn.click()
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    # Instance list should now be visible
    expect(page.locator("[data-testid='instance-list']").first).to_be_visible()


def test_breadcrumb_navigation_on_instance_detail(page: Page, base_url: str) -> None:
    """Multi-instance app detail has breadcrumb back to parent overview."""
    page.goto(base_url + "/apps/multi_app?instance=0")
    page.wait_for_load_state("networkidle")
    breadcrumb = page.locator("nav[aria-label='Breadcrumb']")
    expect(breadcrumb).to_be_visible()
    # Breadcrumb has link back to parent
    parent_link = breadcrumb.locator("[data-testid='breadcrumb-parent']")
    expect(parent_link).to_be_visible()
    parent_link.click()
    expect(page).to_have_url(re.compile(r"/apps/multi_app$"))


# ──────────────────────────────────────────────────────────────────────
# SPA client-side navigation
# ──────────────────────────────────────────────────────────────────────


def test_spa_navigates_without_full_reload(page: Page, base_url: str) -> None:
    """Client-side navigation between pages does not trigger a full page reload."""
    page.goto(base_url + "/apps")
    page.evaluate("window.__test_marker = true")
    page.locator("[data-testid='nav-logs']").click()
    expect(page.locator("[data-testid='log-table']")).to_be_visible()
    assert page.evaluate("window.__test_marker") is True
    page.locator("[data-testid='nav-apps']").click()
    expect(page.locator("body")).to_contain_text("apps")
    assert page.evaluate("window.__test_marker") is True


def test_spa_handles_direct_deep_link(page: Page, base_url: str) -> None:
    """Direct navigation to a deep link (e.g. /apps/my_app) works."""
    page.goto(base_url + "/apps/my_app")
    # App detail title shows the app_key
    expect(page.locator("[data-testid='app-title']")).to_contain_text("my_app")
    # Overview tab renders by default
    expect(page.locator("[data-testid='overview-tab']")).to_be_visible()
