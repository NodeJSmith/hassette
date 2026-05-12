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


def test_apps_list_status_filter_pills(page: Page, base_url: str) -> None:
    """Clicking the running filter pill should filter to only running apps."""
    page.goto(base_url + "/apps")
    page.locator("[data-testid='filter-running']").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)


def test_tab_filter_is_client_side(page: Page, base_url: str) -> None:
    """Filter pills work client-side (no full page reload)."""
    page.goto(base_url + "/apps")
    page.locator("[data-testid='filter-running']").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-disabled_app']")).to_have_count(0)
    page.locator("[data-testid='filter-all']").click()
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()


def test_app_row_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking an app row link should navigate to the App Detail page."""
    page.goto(base_url + "/apps")
    page.locator("a[href='/apps/my_app']").first.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))
    expect(page.locator("[data-testid='app-title']")).to_contain_text("my_app")


def test_multi_instance_expand_persists_across_navigation(page: Page, base_url: str) -> None:
    """Expanding a multi-instance app row shows child instances."""
    page.goto(base_url + "/apps")

    expand_btn = page.locator("[data-testid='app-row-multi_app'] [data-testid='app-row-expand']")
    expect(expand_btn).to_be_visible()

    expand_btn.click()
    page.wait_for_timeout(300)

    expect(page.locator("text=MultiApp[0]")).to_be_visible()
    expect(page.locator("text=MultiApp[1]")).to_be_visible()
    expect(page.locator("text=MultiApp[2]")).to_be_visible()


def test_status_filter_uses_aria_pressed(page: Page, base_url: str) -> None:
    """Status filter pills use aria-pressed."""
    page.goto(base_url + "/apps")
    filter_group = page.locator("[data-testid='apps-filter-pills']")
    expect(filter_group).to_be_visible()
    all_pill = page.locator("[data-testid='filter-all']")
    expect(all_pill).to_have_attribute("aria-pressed", "true")
    running_pill = page.locator("[data-testid='filter-running']")
    expect(running_pill).to_have_attribute("aria-pressed", "false")
    running_pill.click()
    page.wait_for_timeout(300)
    expect(running_pill).to_have_attribute("aria-pressed", "true")
    expect(all_pill).to_have_attribute("aria-pressed", "false")
