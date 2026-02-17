"""E2E tests for page navigation and sidebar behavior."""

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
    ("/ui/scheduler", "Scheduled Jobs"),
    ("/ui/bus", "Event Bus"),
]


def test_root_redirects_to_dashboard(page: Page, base_url: str) -> None:
    response = page.goto(base_url + "/")
    assert response is not None
    assert "/ui/" in page.url


@pytest.mark.parametrize(("path", "heading"), PAGES, ids=[p for p, _ in PAGES])
def test_all_pages_load(page: Page, base_url: str, path: str, heading: str) -> None:
    page.goto(base_url + path)
    expect(page.locator("body")).to_contain_text(heading)


# Sidebar navigation entries: (link text, expected URL path suffix, expected content)
SIDEBAR_LINKS = [
    ("Dashboard", "/ui/", "Activity"),
    ("Apps", "/ui/apps", "App Management"),
    ("Scheduler", "/ui/scheduler", "Scheduled Jobs"),
    ("Bus", "/ui/bus", "Event Bus"),
    ("Logs", "/ui/logs", "Log Viewer"),
]


@pytest.mark.parametrize(
    ("link_text", "expected_path", "expected_content"),
    SIDEBAR_LINKS,
    ids=[t for t, _, _ in SIDEBAR_LINKS],
)
def test_sidebar_navigation(
    page: Page, base_url: str, link_text: str, expected_path: str, expected_content: str
) -> None:
    # Start on dashboard
    page.goto(base_url + "/ui/")
    # Click sidebar link (hx-boost converts to AJAX + pushState)
    page.locator(f".ht-nav-list a:has-text('{link_text}')").click()
    expect(page).to_have_url(re.compile(re.escape(expected_path)))
    expect(page.locator("body")).to_contain_text(expected_content)


# Map sidebar link text to the current_page value used for is-active
SIDEBAR_ACTIVE = [
    ("/ui/", "Dashboard"),
    ("/ui/apps", "Apps"),
    ("/ui/scheduler", "Scheduler"),
    ("/ui/bus", "Bus"),
    ("/ui/logs", "Logs"),
]


@pytest.mark.parametrize(("path", "link_text"), SIDEBAR_ACTIVE, ids=[p for p, _ in SIDEBAR_ACTIVE])
def test_sidebar_active_state(page: Page, base_url: str, path: str, link_text: str) -> None:
    page.goto(base_url + path)
    active_link = page.locator(".ht-nav-list a.is-active")
    expect(active_link).to_contain_text(link_text)


# ──────────────────────────────────────────────────────────────────────
# Sidebar collapse / expand behavior
# ──────────────────────────────────────────────────────────────────────


def test_sidebar_default_open_on_desktop(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))
    expect(page.locator(".ht-brand-text")).to_be_visible()


def _wait_for_sidebar_width(page: Page, expected: int, tolerance: int = 4) -> None:
    """Wait for the sidebar CSS transition to settle at the expected width."""
    page.wait_for_function(
        f"""() => {{
            const el = document.querySelector('.ht-sidebar');
            return el && Math.abs(el.getBoundingClientRect().width - {expected}) <= {tolerance};
        }}""",
        timeout=2000,
    )
    # Small extra pause so the CSS transition is fully complete on slow CI runners.
    page.wait_for_timeout(50)


def test_sidebar_collapse_to_icon_rail(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    page.locator(".ht-menu-toggle").click()
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))
    _wait_for_sidebar_width(page, 56)
    box = sidebar.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(56, abs=4)
    # Brand text hidden, icons still visible
    expect(page.locator(".ht-brand-text")).not_to_be_visible()
    expect(page.locator(".ht-nav-list .ht-icon").first).to_be_visible()


def test_sidebar_expand_from_icon_rail(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    toggle = page.locator(".ht-menu-toggle")
    # Collapse
    toggle.click()
    expect(page.locator(".ht-sidebar")).not_to_have_class(re.compile(r"\bis-open\b"))
    # Expand
    toggle.click()
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))
    _wait_for_sidebar_width(page, 220)
    box = sidebar.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(220, abs=4)
    expect(page.locator(".ht-brand-text")).to_be_visible()


def test_brand_link_navigates_to_dashboard(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/apps")
    page.locator(".ht-brand-link").click()
    expect(page).to_have_url(re.compile(r"/ui/?$"))


def test_sidebar_stays_open_after_desktop_nav(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    page.locator(".ht-nav-list a:has-text('Apps')").click()
    expect(page).to_have_url(re.compile(r"/ui/apps"))
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))


def test_mobile_icon_rail_default(page: Page, base_url: str) -> None:
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))
    expect(page.locator(".ht-brand-text")).not_to_be_visible()
    main = page.locator(".ht-main")
    margin = main.evaluate("el => getComputedStyle(el).marginLeft")
    assert margin == "56px"


def test_mobile_expand_collapse_with_backdrop(page: Page, base_url: str) -> None:
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/ui/")
    # Expand via status bar hamburger
    page.locator(".ht-menu-toggle").click()
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))
    _wait_for_sidebar_width(page, 260)
    box = sidebar.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(260, abs=4)
    # Backdrop visible
    backdrop = page.locator(".ht-sidebar-backdrop")
    expect(backdrop).to_be_visible()
    # Click backdrop to close — target the strip right of the 260px sidebar
    backdrop.click(force=True, position={"x": 320, "y": 300})
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))


def test_mobile_sidebar_toggle_visible_when_expanded(page: Page, base_url: str) -> None:
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(base_url + "/ui/")
    toggle = page.locator(".ht-sidebar-toggle")
    # Hidden when collapsed
    expect(toggle).not_to_be_visible()
    # Expand sidebar
    page.locator(".ht-menu-toggle").click()
    expect(toggle).to_be_visible()
    # Click toggle to close
    toggle.click()
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))


def test_escape_key_closes_sidebar(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))
    page.keyboard.press("Escape")
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))


def test_resize_collapses_sidebar(page: Page, base_url: str) -> None:
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/ui/")
    sidebar = page.locator(".ht-sidebar")
    expect(sidebar).to_have_class(re.compile(r"\bis-open\b"))
    # Resize to mobile width
    page.set_viewport_size(MOBILE_VIEWPORT)
    expect(sidebar).not_to_have_class(re.compile(r"\bis-open\b"))
