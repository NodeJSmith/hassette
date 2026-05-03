"""E2E tests for the Configuration page in the new Ink UI."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_config_page_renders(page: Page, base_url: str) -> None:
    """Config page loads with the Configuration heading."""
    page.goto(base_url + "/config")
    expect(page.locator("body")).to_contain_text("Configuration")


def test_config_page_title(page: Page, base_url: str) -> None:
    """Config page sets the correct document title."""
    page.goto(base_url + "/config")
    expect(page).to_have_title("Config - Hassette")


def test_config_page_shows_general_section(page: Page, base_url: str) -> None:
    """Config page shows the General section with expected keys."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("General")
    expect(body).to_contain_text("log_level")
    expect(body).to_contain_text("dev_mode")


def test_config_page_shows_connection_section(page: Page, base_url: str) -> None:
    """Config page shows the Connection section with expected keys."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("Connection")
    expect(body).to_contain_text("web_api_host")
    expect(body).to_contain_text("web_api_port")


def test_config_page_shows_paths_section(page: Page, base_url: str) -> None:
    """Config page shows the Paths section with app_dir, data_dir, config_dir."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("Paths")
    expect(body).to_contain_text("app_dir")
    expect(body).to_contain_text("data_dir")
    expect(body).to_contain_text("config_dir")


def test_config_page_shows_scheduler_section(page: Page, base_url: str) -> None:
    """Config page shows the Scheduler section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("Scheduler")
    expect(body).to_contain_text("scheduler_min_delay_seconds")


def test_config_page_shows_timeouts_section(page: Page, base_url: str) -> None:
    """Config page shows the Timeouts section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("Timeouts")
    expect(body).to_contain_text("startup_timeout_seconds")


def test_config_page_shows_buffers_section(page: Page, base_url: str) -> None:
    """Config page shows the Buffers section."""
    page.goto(base_url + "/config")
    body = page.locator("body")
    expect(body).to_contain_text("Buffers")
    expect(body).to_contain_text("web_api_event_buffer_size")


def test_config_values_are_non_empty(page: Page, base_url: str) -> None:
    """Config table cells have actual values (not all em-dashes)."""
    page.goto(base_url + "/config")
    # Wait for data to load
    page.wait_for_load_state("networkidle")
    # Value cells exist in the config table
    value_cells = page.locator("td.ht-config-table__value")
    # There should be many config value cells
    count = value_cells.count()
    assert count >= 10, f"Expected at least 10 config value cells, got {count}"
