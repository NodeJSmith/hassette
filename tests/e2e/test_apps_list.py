"""E2E tests for the Apps list page."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_apps_list_renders_all_apps(page: Page, base_url: str) -> None:
    """All configured apps should be visible on the apps list page."""
    page.goto(base_url + "/apps")
    body = page.locator("body")
    expect(body).to_contain_text("my_app")
    expect(body).to_contain_text("other_app")
    expect(body).to_contain_text("broken_app")
    expect(body).to_contain_text("disabled_app")


def test_apps_list_status_filter_tabs(page: Page, base_url: str) -> None:
    """Clicking the Running tab should filter to only running apps."""
    page.goto(base_url + "/apps")
    # Click the "Running" filter tab
    page.locator("[data-testid='tab-running'] a").click()
    # Wait for Preact reactivity to filter
    page.wait_for_timeout(300)
    # Running app should be visible; others should not be in the DOM
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_tab_filter_is_client_side(page: Page, base_url: str) -> None:
    """After setting a tab filter, the list should be filtered client-side.

    In the Preact SPA, filtering is done via signal state, not server-side HTMX.
    """
    page.goto(base_url + "/apps")
    # Click the "Running" filter tab
    page.locator("[data-testid='tab-running'] a").click()
    page.wait_for_timeout(300)
    # Verify filtered state
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)
    # Click "All" tab to reset
    page.locator("[data-testid='tab-all'] a").click()
    page.wait_for_timeout(300)
    # All apps should be visible again
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_be_visible()


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app row link should navigate to the App Detail page."""
    page.goto(base_url + "/apps")
    page.locator("a[href='/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))
    expect(page.locator("body")).to_contain_text("My App")
