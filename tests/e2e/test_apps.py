"""E2E tests for the Apps page in the new Ink UI.

The /apps page shows an app table with filter pills.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_apps_table_shows_manifests(page: Page, base_url: str) -> None:
    """All configured apps should be visible on the apps list page."""
    page.goto(base_url + "/apps")
    body = page.locator("body")
    expect(body).to_contain_text("my_app")
    expect(body).to_contain_text("other_app")
    expect(body).to_contain_text("broken_app")
    expect(body).to_contain_text("disabled_app")


def test_filter_by_status_pill(page: Page, base_url: str) -> None:
    """Clicking the running filter pill shows only running apps."""
    page.goto(base_url + "/apps")
    page.locator(".ht-apps-filter-pill", has_text="running").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_tab_filter_is_client_side(page: Page, base_url: str) -> None:
    """Filter pills work client-side (no full page reload)."""
    page.goto(base_url + "/apps")
    page.locator(".ht-apps-filter-pill", has_text="running").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)
    page.locator(".ht-apps-filter-pill", has_text="all").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app link navigates to the App Detail page."""
    page.goto(base_url + "/apps")
    page.locator("a[href='/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))
    expect(page.locator("[data-testid='app-title']")).to_contain_text("my_app")


def test_app_detail_shows_sections(page: Page, base_url: str) -> None:
    """App detail page shows tab strip with expected tabs."""
    page.goto(base_url + "/apps/my_app")
    body = page.locator("body")
    expect(body).to_contain_text("overview")
    expect(body).to_contain_text("handlers")
    expect(body).to_contain_text("code")
    expect(body).to_contain_text("logs")
    expect(body).to_contain_text("config")


def test_running_app_shows_stop_and_reload_buttons(page: Page, base_url: str) -> None:
    """Running app shows Stop and Reload action buttons."""
    page.goto(base_url + "/apps/my_app")
    expect(page.get_by_label("Stop app")).to_be_visible()
    expect(page.get_by_label("Reload app")).to_be_visible()


def test_failed_app_shows_error_message(page: Page, base_url: str) -> None:
    """Failed app shows its error message."""
    page.goto(base_url + "/apps/broken_app")
    expect(page.locator("body")).to_contain_text("Init error: bad config")


def test_failed_app_shows_start_button(page: Page, base_url: str) -> None:
    """Failed app shows a Start button."""
    page.goto(base_url + "/apps/broken_app")
    expect(page.get_by_label("Start app")).to_be_visible()


def test_app_detail_shows_display_name(page: Page, base_url: str) -> None:
    """App detail header shows the app key."""
    page.goto(base_url + "/apps/my_app")
    expect(page.locator("[data-testid='app-title']")).to_contain_text("my_app")


def test_app_detail_log_entries_show_app_logs(page: Page, base_url: str) -> None:
    """App detail Logs tab shows app-specific log entries."""
    page.goto(base_url + "/apps/my_app/logs")
    page.wait_for_timeout(500)
    expect(page.locator("body")).to_contain_text("MyApp initialized")
    expect(page.locator("body")).to_contain_text("Light kitchen unresponsive")
    expect(page.locator("body")).to_contain_text("Failed to call service")
    expect(page.locator("body")).not_to_contain_text("Hassette started successfully")
    expect(page.locator("body")).not_to_contain_text("WebSocket heartbeat sent")


def test_status_filter_uses_aria_pressed(page: Page, base_url: str) -> None:
    """Status filter pills use aria-pressed."""
    page.goto(base_url + "/apps")
    filter_group = page.locator("[data-testid='apps-filter-pills']")
    expect(filter_group).to_be_visible()
    all_pill = page.locator(".ht-apps-filter-pill", has_text="all")
    expect(all_pill).to_have_attribute("aria-pressed", "true")
    running_pill = page.locator(".ht-apps-filter-pill", has_text="running")
    expect(running_pill).to_have_attribute("aria-pressed", "false")
    running_pill.click()
    page.wait_for_timeout(300)
    expect(running_pill).to_have_attribute("aria-pressed", "true")
    expect(all_pill).to_have_attribute("aria-pressed", "false")
