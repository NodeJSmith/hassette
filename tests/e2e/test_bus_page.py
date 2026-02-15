"""E2E tests for the Event Bus page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_bus_page_heading(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/bus")
    expect(page.locator("body")).to_contain_text("Event Bus")


def test_bus_listeners_table_shows_seed_data(page: Page, base_url: str) -> None:
    """Verify listener metrics table renders seed data from conftest."""
    page.goto(base_url + "/ui/bus")
    listeners_table = page.locator("#bus-listeners")
    expect(listeners_table).to_contain_text("on_light_change")
    expect(listeners_table).to_contain_text("on_temp_update")


def test_bus_listeners_show_invocation_counts(page: Page, base_url: str) -> None:
    """Seed data has 10 and 20 invocations respectively."""
    page.goto(base_url + "/ui/bus")
    listeners_table = page.locator("#bus-listeners")
    # Check that numeric invocation counts are visible
    expect(listeners_table).to_contain_text("10")
    expect(listeners_table).to_contain_text("20")


def test_bus_listeners_show_topic(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/bus")
    listeners_table = page.locator("#bus-listeners")
    # Topics from seed: state_changed.light.kitchen, state_changed.sensor.temperature
    expect(listeners_table).to_contain_text("light.kitchen")
    expect(listeners_table).to_contain_text("sensor.temperature")


def test_bus_table_headers(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/bus")
    for header in ("Handler", "App", "Topic", "Invocations", "Success", "Failed", "Avg Duration"):
        expect(page.locator(f"th:has-text('{header}')").first).to_be_visible()


def test_bus_listeners_show_owner_link(page: Page, base_url: str) -> None:
    """Verify the owner column renders as a link to the app detail."""
    page.goto(base_url + "/ui/bus")
    listeners_table = page.locator("#bus-listeners")
    owner_link = listeners_table.locator("a[href*='/ui/apps/']").first
    expect(owner_link).to_be_visible()
