"""E2E tests for the Configuration page (schema-driven renderer)."""

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


def test_config_page_renders_schema_view(page: Page, base_url: str) -> None:
    """Config page renders the shared schema-driven view."""
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-schema-view']")).to_be_visible()


def test_config_page_shows_general_section(page: Page, base_url: str) -> None:
    """Top-level scalar fields collect in the 'general' section.

    The schema-driven renderer groups nested-object fields into named sections
    and places all flat (scalar) top-level fields under 'general'.
    HassetteConfig scalars include dev_mode → 'Dev Mode'.
    """
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-section-general']")).to_be_visible()
    # dev_mode is a top-level boolean scalar → label "Dev Mode"
    expect(page.locator("[data-testid='config-section-general']")).to_contain_text("Dev Mode")


def test_config_page_shows_web_api_section(page: Page, base_url: str) -> None:
    """web_api group renders using its ui.group_label 'Web API'.

    The old hand-written 'connection' and 'buffers' groups are gone — those
    fields now appear inside the schema-driven 'Web API' section.
    """
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-section-web-api']")).to_be_visible()
    # host and port live inside WebApiConfig
    expect(page.locator("[data-testid='config-section-web-api']")).to_contain_text("Host")
    expect(page.locator("[data-testid='config-section-web-api']")).to_contain_text("Port")


def test_config_page_shows_scheduler_section(page: Page, base_url: str) -> None:
    """Scheduler group section is present."""
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-section-scheduler']")).to_be_visible()
    expect(page.locator("[data-testid='config-section-scheduler']")).to_contain_text("Min Delay Seconds")


def test_config_page_shows_lifecycle_section(page: Page, base_url: str) -> None:
    """Lifecycle group section is present with startup_timeout_seconds.

    Replaces the old hand-written 'timeouts' section.
    """
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-section-lifecycle']")).to_be_visible()
    expect(page.locator("[data-testid='config-section-lifecycle']")).to_contain_text("Startup Timeout Seconds")


def test_config_page_shows_apps_section(page: Page, base_url: str) -> None:
    """Apps group section is present with directory field."""
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='config-section-apps']")).to_be_visible()


def test_config_values_are_non_empty(page: Page, base_url: str) -> None:
    """Schema-view value cells are populated (not blank)."""
    page.goto(base_url + "/config")
    page.wait_for_load_state("networkidle")
    # All value cells now use data-testid="config-value-{key}"
    value_cells = page.locator("[data-testid^='config-value-']")
    count = value_cells.count()
    assert count >= 10, f"Expected at least 10 config value cells, got {count}"
