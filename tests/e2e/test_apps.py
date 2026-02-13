"""E2E tests for the Apps page and app detail."""

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
    # Click the "Running" filter tab
    page.locator("#tab-running a").click()
    # Wait for HTMX swap to complete
    page.wait_for_load_state("networkidle")
    manifest_list = page.locator("#manifest-list")
    expect(manifest_list).to_contain_text("my_app")
    expect(manifest_list).not_to_contain_text("other_app")
    expect(manifest_list).not_to_contain_text("disabled_app")


def test_app_detail_navigation(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps")
    # Click the app link to navigate to detail page
    page.locator("a[href='/ui/apps/my_app']").first.click()
    page.wait_for_load_state("networkidle")
    assert "/ui/apps/my_app" in page.url
    expect(page.locator("body")).to_contain_text("My App")


def test_app_detail_shows_sections(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/apps/my_app")
    body = page.locator("body")
    expect(body).to_contain_text("Configuration")
    expect(body).to_contain_text("Bus Listeners")
    expect(body).to_contain_text("Scheduled Jobs")
    expect(body).to_contain_text("Recent Logs")
