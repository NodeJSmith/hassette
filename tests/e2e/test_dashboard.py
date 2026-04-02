"""E2E tests for the Dashboard page panels."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Connection bar ──────────────────────────────────────────────────


def test_dashboard_renders_status_bar(page: Page, base_url: str) -> None:
    """Status bar is visible with connection state text and theme toggle.

    Note: The e2e test server disables WebSocket (ws='none'), so the Preact
    WS hook will not connect and the bar shows 'Disconnected'.
    In production with a real WS connection it would show 'Connected'.
    """
    page.goto(base_url + "/")
    status_bar = page.locator(".ht-status-bar")
    expect(status_bar).to_be_visible()
    # Bar should show a connection status (Connected, Disconnected, or Reconnecting)
    expect(status_bar).to_contain_text("onnect")
    # Theme toggle should be present
    expect(page.locator("[data-testid='theme-toggle']")).to_be_visible()


# ── KPI strip ───────────────────────────────────────────────────────


def test_dashboard_renders_kpi_strip(page: Page, base_url: str) -> None:
    """5 KPI cards visible with labels."""
    page.goto(base_url + "/")
    kpi_strip = page.locator("[data-testid='kpi-strip']")
    expect(kpi_strip).to_be_visible()

    kpi_labels = ["Apps", "Error Rate", "Handlers", "Jobs", "Uptime"]
    for label in kpi_labels:
        expect(kpi_strip).to_contain_text(label)


def test_dashboard_error_rate_includes_jobs(page: Page, base_url: str) -> None:
    """Error rate denominator includes both handler invocations AND job executions.

    Seed data: 33 invocations + 28 executions = 61 total, 3 + 6 = 9 errors.
    The detail text must show "9 / 61 invocations", NOT "3 / 33 invocations".
    """
    page.goto(base_url + "/")
    kpi_strip = page.locator("[data-testid='kpi-strip']")
    expect(kpi_strip).to_be_visible()

    # Combined denominator: 33 handler invocations + 28 job executions = 61
    expect(kpi_strip).to_contain_text("9 / 61 invocations")
    # Must NOT show handler-only denominator
    expect(kpi_strip).not_to_contain_text("3 / 33 invocations")


# ── App health grid ─────────────────────────────────────────────────


def test_dashboard_renders_app_grid(page: Page, base_url: str) -> None:
    """App cards visible with names and status badges."""
    page.goto(base_url + "/")
    grid = page.locator("#dashboard-app-grid")
    expect(grid).to_be_visible()

    # All seeded apps should appear as cards
    expect(grid.locator("[data-testid='app-card-my_app']")).to_be_visible()
    expect(grid.locator("[data-testid='app-card-broken_app']")).to_be_visible()
    expect(grid.locator("[data-testid='app-card-other_app']")).to_be_visible()
    expect(grid.locator("[data-testid='app-card-disabled_app']")).to_be_visible()


def test_app_card_links_to_detail(page: Page, base_url: str) -> None:
    """Clicking app card navigates to App Detail."""
    page.goto(base_url + "/")
    card = page.locator("[data-testid='app-card-my_app'] a")
    expect(card).to_be_visible()
    card.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))


def test_app_card_shows_status_badge(page: Page, base_url: str) -> None:
    """App cards display status badges."""
    page.goto(base_url + "/")
    # Running app should have success badge (pill badge via StatusBadge)
    running_card = page.locator("[data-testid='app-card-my_app']")
    expect(running_card.locator(".ht-badge--success")).to_be_visible()

    # Failed app should have danger badge
    failed_card = page.locator("[data-testid='app-card-broken_app']")
    expect(failed_card.locator(".ht-badge--danger")).to_be_visible()


def test_app_card_shows_invocation_and_execution_counts(page: Page, base_url: str) -> None:
    """App cards with activity display invocation and execution counts."""
    page.goto(base_url + "/")

    # my_app has seed data: 30 invocations, 20 executions
    my_app_card = page.locator("[data-testid='app-card-my_app']")
    counts = my_app_card.locator("[data-testid='app-card-counts']")
    expect(counts).to_be_visible()
    expect(counts).to_contain_text("30 inv")
    expect(counts).to_contain_text("20 exec")

    # broken_app has seed data: 3 invocations, 8 executions
    broken_card = page.locator("[data-testid='app-card-broken_app']")
    broken_counts = broken_card.locator("[data-testid='app-card-counts']")
    expect(broken_counts).to_be_visible()
    expect(broken_counts).to_contain_text("3 inv")
    expect(broken_counts).to_contain_text("8 exec")

    # other_app has zero invocations and executions — no count row
    other_card = page.locator("[data-testid='app-card-other_app']")
    expect(other_card).to_be_visible()
    expect(other_card.locator("[data-testid='app-card-counts']")).to_have_count(0)

    # disabled_app has zero invocations and executions — no count row
    disabled_card = page.locator("[data-testid='app-card-disabled_app']")
    expect(disabled_card).to_be_visible()
    expect(disabled_card.locator("[data-testid='app-card-counts']")).to_have_count(0)


# ── Error feed ──────────────────────────────────────────────────────


def test_dashboard_renders_error_feed(page: Page, base_url: str) -> None:
    """Error items visible with app name and message."""
    page.goto(base_url + "/")
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()

    # Should contain seeded error data
    error_items = error_feed.locator("[data-testid='error-item']")
    expect(error_items).to_have_count(3)

    # Check errors from multiple apps
    expect(error_feed).to_contain_text("my_app")
    expect(error_feed).to_contain_text("Bad state value")
    expect(error_feed).to_contain_text("Light service unavailable")
    expect(error_feed).to_contain_text("broken_app")
    expect(error_feed).to_contain_text("Lock service timed out")


# ── Session info ────────────────────────────────────────────────────


def test_dashboard_renders_session_info(page: Page, base_url: str) -> None:
    """Session bar shows session number and uptime."""
    page.goto(base_url + "/")
    session_bar = page.locator("[data-testid='session-info']")
    expect(session_bar).to_be_visible()
    # Should show Hassette version
    expect(session_bar).to_contain_text("Hassette")


# ── Existing tests (preserved from original) ────────────────────────

PANEL_HEADINGS = [
    "App Health",
    "Recent Errors",
]


def test_dashboard_panels_visible(page: Page, base_url: str) -> None:
    """Verify key panel headings are visible on the dashboard."""
    page.goto(base_url + "/")
    body = page.locator("body")
    for heading in PANEL_HEADINGS:
        expect(body).to_contain_text(heading)


VIEW_ALL_LINKS = [
    ("App Health", "/apps"),
]


@pytest.mark.parametrize(
    ("panel_heading", "target_path"),
    VIEW_ALL_LINKS,
    ids=[h for h, _ in VIEW_ALL_LINKS],
)
def test_dashboard_view_all_links(page: Page, base_url: str, panel_heading: str, target_path: str) -> None:
    """'View All' / 'Manage Apps' links navigate to the correct full page."""
    page.goto(base_url + "/")
    panel = page.locator(f".ht-card:has(h2:has-text('{panel_heading}'))")
    link = panel.locator("a.ht-btn")
    expect(link).to_be_visible()
    link.click()
    expect(page).to_have_url(re.compile(re.escape(target_path)))
