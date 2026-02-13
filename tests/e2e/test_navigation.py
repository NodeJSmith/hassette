"""E2E tests for page navigation and sidebar behavior."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

PAGES = [
    ("/ui/", "Dashboard"),
    ("/ui/apps", "App Management"),
    ("/ui/logs", "Log Viewer"),
    ("/ui/scheduler", "Scheduled Jobs"),
    ("/ui/bus", "Event Bus"),
    ("/ui/entities", "Entity Browser"),
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
    ("Dashboard", "/ui/", "System Health"),
    ("Apps", "/ui/apps", "App Management"),
    ("Scheduler", "/ui/scheduler", "Scheduled Jobs"),
    ("Bus", "/ui/bus", "Event Bus"),
    ("Entities", "/ui/entities", "Entity Browser"),
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
    # Click sidebar link
    page.locator(f".menu-list a:has-text('{link_text}')").click()
    page.wait_for_load_state("networkidle")
    assert page.url.endswith(expected_path) or expected_path in page.url
    expect(page.locator("body")).to_contain_text(expected_content)


# Map sidebar link text to the current_page value used for is-active
SIDEBAR_ACTIVE = [
    ("/ui/", "Dashboard"),
    ("/ui/apps", "Apps"),
    ("/ui/scheduler", "Scheduler"),
    ("/ui/bus", "Bus"),
    ("/ui/entities", "Entities"),
    ("/ui/logs", "Logs"),
]


@pytest.mark.parametrize(("path", "link_text"), SIDEBAR_ACTIVE, ids=[p for p, _ in SIDEBAR_ACTIVE])
def test_sidebar_active_state(page: Page, base_url: str, path: str, link_text: str) -> None:
    page.goto(base_url + path)
    active_link = page.locator(".menu-list a.is-active")
    expect(active_link).to_contain_text(link_text)
