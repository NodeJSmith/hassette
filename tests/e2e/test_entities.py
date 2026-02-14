"""E2E tests for the Entity Browser page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_entities_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/entities")
    expect(page.locator("body")).to_contain_text("Entity Browser")
    expect(page.locator("body")).to_contain_text("5 entities")


def test_filter_by_domain(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/entities")
    domain_select = page.locator("#entity-domain-filter")
    expect(domain_select).to_be_visible()

    # Select "light" domain
    domain_select.select_option("light")
    # Wait for HTMX swap to populate the entity list
    entity_list = page.locator("#entity-list")
    expect(entity_list).to_contain_text("light.kitchen")
    expect(entity_list).to_contain_text("light.bedroom")
    expect(entity_list).not_to_contain_text("sensor.temperature")


def test_search_entities(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/entities")
    search_input = page.locator("#entity-search")
    expect(search_input).to_be_visible()

    # Type search term — triggers 300ms debounced refresh
    search_input.fill("kitchen")
    # Wait for HTMX swap to complete with matching results
    entity_list = page.locator("#entity-list")
    expect(entity_list).to_contain_text("light.kitchen")
    expect(entity_list).not_to_contain_text("light.bedroom")
    expect(entity_list).not_to_contain_text("sensor.temperature")


def test_domain_filter_has_expected_options(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/entities")
    domain_select = page.locator("#entity-domain-filter")
    # Should have options for each domain in the mock data
    for domain in ("binary_sensor", "light", "sensor", "switch"):
        expect(domain_select.locator(f"option[value='{domain}']")).to_have_count(1)
