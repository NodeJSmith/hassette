"""E2E tests for the Dashboard page panels."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

PANEL_HEADINGS = [
    "Apps",
    "Activity",
    "Recent Logs",
]


def test_dashboard_panels_visible(page: Page, base_url: str) -> None:
    """Verify all panel headings are visible on the dashboard."""
    page.goto(base_url + "/ui/")
    body = page.locator("body")
    for heading in PANEL_HEADINGS:
        expect(body).to_contain_text(heading)


def test_dashboard_app_grid_shows_apps(page: Page, base_url: str) -> None:
    """Verify app grid shows cards for each app from seed data."""
    page.goto(base_url + "/ui/")
    grid = page.locator("#dashboard-app-grid")
    expect(grid).to_contain_text("My App")
    expect(grid).to_contain_text("Broken App")
    expect(grid).to_contain_text("Other App")
    expect(grid).to_contain_text("Disabled App")


def test_dashboard_app_grid_failed_chip_visible(page: Page, base_url: str) -> None:
    """Verify failed app chip is rendered with danger border class."""
    page.goto(base_url + "/ui/")
    failed_chip = page.locator(".ht-app-chip--failed")
    expect(failed_chip).to_be_visible()
    expect(failed_chip).to_contain_text("Broken App")


def test_dashboard_logs_panel_content(page: Page, base_url: str) -> None:
    """Verify logs panel shows log entries from seed data."""
    page.goto(base_url + "/ui/")
    logs_panel = page.locator("#dashboard-logs")
    expect(logs_panel).to_contain_text("Hassette started successfully")


def test_dashboard_logs_panel_has_table_headers(page: Page, base_url: str) -> None:
    """Verify logs panel renders a table with column headers."""
    page.goto(base_url + "/ui/")
    logs_panel = page.locator("#dashboard-logs")
    expect(logs_panel.locator("th:has-text('Level')")).to_be_visible()
    expect(logs_panel.locator("th:has-text('Time')")).to_be_visible()
    expect(logs_panel.locator("th:has-text('App')")).to_be_visible()
    expect(logs_panel.locator("th:has-text('Message')")).to_be_visible()


VIEW_ALL_LINKS = [
    ("Recent Logs", "/ui/logs"),
    ("Apps", "/ui/apps"),
]


@pytest.mark.parametrize(
    ("panel_heading", "target_path"),
    VIEW_ALL_LINKS,
    ids=[h for h, _ in VIEW_ALL_LINKS],
)
def test_dashboard_view_all_links(page: Page, base_url: str, panel_heading: str, target_path: str) -> None:
    """Each 'View All' / 'Manage Apps' link navigates to the correct full page."""
    page.goto(base_url + "/ui/")
    # Find the panel box containing the heading, then click its link
    panel = page.locator(f".ht-card:has(h2:has-text('{panel_heading}'))")
    link = panel.locator("a.ht-btn")
    expect(link).to_be_visible()
    link.click()
    expect(page).to_have_url(re.compile(re.escape(target_path)))
