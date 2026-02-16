"""E2E tests for the Entity Browser page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Number of extra light entities injected by many_light_entities fixture.
# Must exceed 2x the default entity-list partial limit (50) so the "Load more"
# button appears on two consecutive pages when filtering by the "light" domain.
# Total lights = _EXTRA_LIGHT_COUNT + 2 original (bedroom, kitchen).
_EXTRA_LIGHT_COUNT = 120


@pytest.fixture
def many_light_entities(mock_hassette):
    """Temporarily inject many light entities so pagination triggers."""
    states = mock_hassette._state_proxy.states
    added_keys: list[str] = []
    for i in range(_EXTRA_LIGHT_COUNT):
        eid = f"light.room_{i:03d}"
        states[eid] = {
            "entity_id": eid,
            "state": "on" if i % 2 == 0 else "off",
            "attributes": {"friendly_name": f"Room {i:03d} Light"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        }
        added_keys.append(eid)
    yield added_keys
    for eid in added_keys:
        states.pop(eid, None)


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


def test_load_more_appends_entities(page: Page, base_url: str, many_light_entities: list[str]) -> None:  # noqa: ARG001
    """Clicking 'Load more' multiple times should keep appending rows."""
    page.goto(base_url + "/ui/entities")
    domain_select = page.locator("#entity-domain-filter")
    domain_select.select_option("light")

    entity_list = page.locator("#entity-list")

    # Total light entities = 2 original + 120 extra = 122, sorted alphabetically.
    # With default limit=50, page 1 shows first 50 entities with 72 remaining.
    # Sorted order: light.bedroom, light.kitchen, light.room_000 … light.room_047
    expect(entity_list).to_contain_text("light.bedroom")

    load_more = entity_list.locator("button:has-text('Load more')")
    expect(load_more).to_be_visible()
    expect(load_more).to_contain_text("72 remaining")

    # --- First "Load more" click ---
    load_more.click()

    # Page 2 entities (light.room_048 … light.room_097) should appear.
    expect(entity_list).to_contain_text("light.room_048")
    expect(entity_list).to_contain_text("light.room_097")

    # Page 1 entities must still be present.
    expect(entity_list).to_contain_text("light.bedroom")
    expect(entity_list).to_contain_text("light.room_000")

    # "Load more" should still be visible with 22 remaining.
    load_more = entity_list.locator("button:has-text('Load more')")
    expect(load_more).to_be_visible()
    expect(load_more).to_contain_text("22 remaining")

    # --- Second "Load more" click ---
    load_more.click()

    # Final batch (light.room_098 … light.room_119) should appear.
    expect(entity_list).to_contain_text("light.room_119")

    # ALL previous pages must still be present.
    expect(entity_list).to_contain_text("light.bedroom")
    expect(entity_list).to_contain_text("light.room_000")
    expect(entity_list).to_contain_text("light.room_048")

    # No more "Load more" button — all entities are loaded.
    expect(entity_list.locator("button:has-text('Load more')")).to_have_count(0)
