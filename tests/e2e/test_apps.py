"""E2E tests for the Apps page in the new Ink UI.

The /apps page shows a manifest list with status filter tabs.
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


def test_filter_by_status_tab(page: Page, base_url: str) -> None:
    """Clicking the Running filter tab shows only running apps."""
    page.goto(base_url + "/apps")
    page.locator("[data-testid='tab-running'] button").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_tab_filter_is_client_side(page: Page, base_url: str) -> None:
    """Tab filter works client-side (no full page reload)."""
    page.goto(base_url + "/apps")
    page.locator("[data-testid='tab-running'] button").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    # Reset to All
    page.locator("[data-testid='tab-all'] button").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_be_visible()


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app row navigates to the App Detail page."""
    page.goto(base_url + "/apps")
    page.locator("a[href='/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))
    expect(page.locator("body")).to_contain_text("My App")


def test_app_detail_shows_sections(page: Page, base_url: str) -> None:
    """App detail page shows the Handlers tab by default."""
    page.goto(base_url + "/apps/my_app")
    body = page.locator("body")
    # Tab strip with Handlers, Code, Logs, Config
    expect(body).to_contain_text("Handlers")
    expect(body).to_contain_text("Code")
    expect(body).to_contain_text("Logs")
    expect(body).to_contain_text("Config")


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
    """App detail header shows the app's display name."""
    page.goto(base_url + "/apps/my_app")
    expect(page.locator("body")).to_contain_text("My App")


def test_app_detail_log_entries_show_app_logs(page: Page, base_url: str) -> None:
    """App detail Logs tab shows app-specific log entries."""
    page.goto(base_url + "/apps/my_app")
    logs_tab_btn = page.locator("button[role='tab']", has_text="Logs")
    logs_tab_btn.click()
    page.wait_for_timeout(500)
    entries_badge = page.locator("text=/\\d+ entries/")
    expect(entries_badge).to_be_visible(timeout=5000)
    expect(page.locator("body")).to_contain_text("MyApp initialized")
    expect(page.locator("body")).to_contain_text("Light kitchen unresponsive")
    expect(page.locator("body")).to_contain_text("Failed to call service")
    # Core-only messages should NOT appear
    expect(page.locator("body")).not_to_contain_text("Hassette started successfully")
    expect(page.locator("body")).not_to_contain_text("WebSocket heartbeat sent")


def test_status_filter_uses_aria_pressed(page: Page, base_url: str) -> None:
    """Status filter buttons use aria-pressed."""
    page.goto(base_url + "/apps")
    filter_group = page.locator("[role='group'][aria-label='App status filter']")
    expect(filter_group).to_be_visible()
    all_btn = page.locator("[data-testid='tab-all'] button")
    expect(all_btn).to_have_attribute("aria-pressed", "true")
    running_btn = page.locator("[data-testid='tab-running'] button")
    expect(running_btn).to_have_attribute("aria-pressed", "false")
    running_btn.click()
    page.wait_for_timeout(300)
    expect(running_btn).to_have_attribute("aria-pressed", "true")
    expect(all_btn).to_have_attribute("aria-pressed", "false")
