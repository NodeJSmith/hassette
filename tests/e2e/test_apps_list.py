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
    """Clicking the Running tab should filter to only running apps."""
    page.goto(base_url + "/ui/apps")
    # Click the "Running" filter tab (Alpine.js client-side filtering)
    page.locator("[data-testid='tab-running'] a").click()
    # Wait for Alpine reactivity
    page.wait_for_timeout(200)
    # Running app should be visible, others hidden
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_be_hidden()
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_be_hidden()


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app row link should navigate to the App Detail page."""
    page.goto(base_url + "/ui/apps")
    page.locator("a[href='/ui/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/ui/apps/my_app"))
    expect(page.locator("body")).to_contain_text("My App")
