"""E2E tests for the Dashboard page panels."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

PANEL_HEADINGS = [
    "System Health",
    "Apps",
    "Event Bus",
    "Recent Events",
    "Scheduled Jobs",
    "Recent Logs",
]


def test_dashboard_panels_visible(page: Page, base_url: str) -> None:
    """Verify all 6 panel headings are visible on the dashboard."""
    page.goto(base_url + "/ui/")
    body = page.locator("body")
    for heading in PANEL_HEADINGS:
        expect(body).to_contain_text(heading)


def test_dashboard_scheduler_panel_content(page: Page, base_url: str) -> None:
    """Verify scheduled jobs panel shows summary counts from seed data."""
    page.goto(base_url + "/ui/")
    scheduler_panel = page.locator("#dashboard-scheduler")
    expect(scheduler_panel).to_contain_text("Active")
    expect(scheduler_panel).to_contain_text("Total")
    expect(scheduler_panel).to_contain_text("Repeating")


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
    ("Scheduled Jobs", "/ui/scheduler"),
    ("Recent Logs", "/ui/logs"),
    ("Event Bus", "/ui/bus"),
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
    panel = page.locator(f".box:has(h2:has-text('{panel_heading}'))")
    link = panel.locator("a.button")
    expect(link).to_be_visible()
    link.click()
    page.wait_for_load_state("networkidle")
    assert target_path in page.url
