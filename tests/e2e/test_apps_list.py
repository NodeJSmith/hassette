"""E2E tests for the Apps list page."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_apps_list_renders_all_apps(page: Page, base_url: str) -> None:
    """All configured apps should be visible on the apps list page."""
    page.goto(base_url + "/ui/apps")
    body = page.locator("body")
    expect(body).to_contain_text("my_app")
    expect(body).to_contain_text("other_app")
    expect(body).to_contain_text("broken_app")
    expect(body).to_contain_text("disabled_app")


def test_apps_list_status_filter_tabs(page: Page, base_url: str) -> None:
    """Clicking the Running tab should server-filter to only running apps."""
    page.goto(base_url + "/ui/apps")
    # Click the "Running" filter tab (triggers htmx.ajax server-side filter)
    page.locator("[data-testid='tab-running'] a").click()
    # Wait for the HTMX swap to complete
    page.wait_for_load_state("networkidle")
    # Running app should be visible; others should not be in the DOM
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_tab_filter_persists_after_ws_refresh(page: Page, base_url: str) -> None:
    """After setting a tab filter, a simulated live-update should still respect the filter."""
    page.goto(base_url + "/ui/apps")
    # Click the "Running" filter tab
    page.locator("[data-testid='tab-running'] a").click()
    page.wait_for_load_state("networkidle")
    # Verify filtered state
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    # Verify the data-live-on-app attribute includes the status filter param
    manifest_list = page.locator("#manifest-list")
    live_url = manifest_list.get_attribute("data-live-on-app")
    assert live_url is not None
    assert "?status=running" in live_url, f"Expected ?status=running in URL, got: {live_url}"


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app row link should navigate to the App Detail page."""
    page.goto(base_url + "/ui/apps")
    page.locator("a[href='/ui/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/ui/apps/my_app"))
    expect(page.locator("body")).to_contain_text("My App")
