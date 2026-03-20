"""E2E tests for the Apps page and app detail."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_apps_table_shows_manifests(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps")
    body = page.locator("body")
    expect(body).to_contain_text("my_app")
    expect(body).to_contain_text("other_app")
    expect(body).to_contain_text("broken_app")
    expect(body).to_contain_text("disabled_app")


def test_filter_by_status_tab(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps")
    # Click the "Running" filter tab (triggers htmx.ajax server-side filter)
    page.locator("[data-testid='tab-running'] a").click()
    # Wait for the HTMX swap to complete
    page.wait_for_load_state("networkidle")
    # Running app should be visible; filtered-out apps removed from DOM
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_app_detail_navigation(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps")
    # Click the app link to navigate to detail page
    page.locator("a[href='/ui/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/ui/apps/my_app"))
    expect(page.locator("body")).to_contain_text("My App")


def test_app_detail_shows_sections(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/my_app")
    body = page.locator("body")
    expect(body).to_contain_text("Event Handlers")
    expect(body).to_contain_text("Scheduled Jobs")
    expect(body).to_contain_text("Logs")


def test_running_app_has_success_badge(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/my_app")
    badge = page.locator(".ht-status-badge--running:has-text('running')").first
    expect(badge).to_be_visible()


def test_running_app_shows_stop_and_reload_buttons(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/my_app")
    expect(page.locator("button:has-text('Stop')")).to_be_visible()
    expect(page.locator("button:has-text('Reload')")).to_be_visible()


def test_failed_app_shows_error_message(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/broken_app")
    body = page.locator("body")
    expect(body).to_contain_text("Init error: bad config")


def test_failed_app_has_danger_badge(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/broken_app")
    badge = page.locator(".ht-status-badge--failed:has-text('failed')").first
    expect(badge).to_be_visible()


def test_failed_app_shows_start_button(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/broken_app")
    expect(page.locator("button:has-text('Start')")).to_be_visible()


def test_stopped_app_has_stopped_badge(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/other_app")
    badge = page.locator(".ht-status-badge--stopped:has-text('stopped')").first
    expect(badge).to_be_visible()


def test_disabled_app_has_disabled_badge(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/disabled_app")
    badge = page.locator(".ht-status-badge--disabled:has-text('disabled')").first
    expect(badge).to_be_visible()


def test_app_detail_log_entries_show_app_logs(page: Page, base_url: str) -> None:
    """App detail page should show app-specific log entries after Alpine fetch completes."""
    page.goto(base_url + "/ui/apps/my_app")
    # Wait for Alpine logTable to finish loading (loading badge disappears, entries badge appears)
    entries_badge = page.locator("text=/\\d+ entries/")
    expect(entries_badge).to_be_visible(timeout=5000)
    body = page.locator("body")
    # App-specific log messages should be present
    expect(body).to_contain_text("MyApp initialized")
    expect(body).to_contain_text("Light kitchen unresponsive")
    expect(body).to_contain_text("Failed to call service")
    # Core-only log messages should NOT appear (filtered by app_key)
    expect(body).not_to_contain_text("Hassette started successfully")
    expect(body).not_to_contain_text("WebSocket heartbeat sent")


def test_app_detail_shows_display_name(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/my_app")
    body = page.locator("body")
    expect(body).to_contain_text("My App")  # display name in header
