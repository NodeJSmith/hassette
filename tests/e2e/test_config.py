"""E2E tests for the Configuration page in the new Ink UI."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_config_page_renders(page: Page, base_url: str) -> None:
    """Config page loads with the config heading."""
    page.goto(base_url + "/config")
    expect(page.locator("body")).to_contain_text("config")


def test_config_page_title(page: Page, base_url: str) -> None:
    """Config page sets the correct document title."""
    page.goto(base_url + "/config")
    expect(page).to_have_title("Config - Hassette")


def test_config_page_shows_general_section(page: Page, base_url: str) -> None:
    """Config page shows the general section with expected keys."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("general")
    expect(body).to_contain_text("log_level")
    expect(body).to_contain_text("dev_mode")


def test_config_page_shows_connection_section(page: Page, base_url: str) -> None:
    """Config page shows the connection section with expected keys."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("connection")
    expect(body).to_contain_text("web_api_host")
    expect(body).to_contain_text("web_api_port")


def test_config_page_shows_paths_section(page: Page, base_url: str) -> None:
    """Config page shows the paths section with app_dir, data_dir, config_dir."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("paths")
    expect(body).to_contain_text("app_dir")
    expect(body).to_contain_text("data_dir")
    expect(body).to_contain_text("config_dir")


def test_config_page_shows_scheduler_section(page: Page, base_url: str) -> None:
    """Config page shows the scheduler section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("scheduler")
    expect(body).to_contain_text("scheduler_min_delay_seconds")


def test_config_page_shows_timeouts_section(page: Page, base_url: str) -> None:
    """Config page shows the timeouts section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("timeouts")
    expect(body).to_contain_text("startup_timeout_seconds")


def test_config_page_shows_buffers_section(page: Page, base_url: str) -> None:
    """Config page shows the buffers section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("buffers")
    expect(body).to_contain_text("web_api_event_buffer_size")


def test_config_values_are_non_empty(page: Page, base_url: str) -> None:
    """Config table cells have actual values (not all em-dashes)."""
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    value_cells = page.locator("td.ht-config-table__value")
    count = value_cells.count()
    assert count >= 10, f"Expected at least 10 config value cells, got {count}"
