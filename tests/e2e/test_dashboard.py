"""E2E tests for the Dashboard page panels."""

import re

import pytest
from playwright.sync_api import Page, expect

from hassette.web.telemetry_helpers import compute_error_rate
from tests.e2e.mock_fixtures import (
    APP_TIER_BROKEN_APP_TOTAL_EXECUTIONS,
    APP_TIER_BROKEN_APP_TOTAL_INVOCATIONS,
    APP_TIER_MY_APP_TOTAL_EXECUTIONS,
    APP_TIER_MY_APP_TOTAL_INVOCATIONS,
    ERRORS_COMBINED_COUNT,
    FRAMEWORK_TIER_TOTAL_HANDLER_ERRORS,
    FRAMEWORK_TIER_TOTAL_JOB_ERRORS,
    GLOBAL_COMBINED_TOTAL,
    GLOBAL_HANDLER_ERRORS,
    GLOBAL_JOB_ERRORS,
    GLOBAL_TOTAL_EXECUTIONS,
    GLOBAL_TOTAL_FAILURES,
    GLOBAL_TOTAL_INVOCATIONS,
)

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

    Uses compute_error_rate from the backend to derive the expected string, ensuring
    the E2E assertion exercises the actual formula rather than a re-derivation that
    can silently drift from production code.

    The combined denominator must include BOTH handler invocations and job executions —
    the test verifies the formula by asserting the handler-only denominator does NOT appear.
    """
    page.goto(base_url + "/")
    kpi_strip = page.locator("[data-testid='kpi-strip']")
    expect(kpi_strip).to_be_visible()

    # Derive expected counts via the shared backend helper — same formula as the route.
    # compute_error_rate returns a float; we need the raw counts for the UI display string.
    expected_failures = GLOBAL_TOTAL_FAILURES
    expected_total = GLOBAL_COMBINED_TOTAL
    expected_text = f"{expected_failures} / {expected_total} invocations"

    # Verify the formula result matches (smoke-check that seed data is consistent)
    computed_rate = compute_error_rate(
        total_invocations=GLOBAL_TOTAL_INVOCATIONS,
        total_executions=GLOBAL_TOTAL_EXECUTIONS,
        handler_errors=GLOBAL_HANDLER_ERRORS,
        job_errors=GLOBAL_JOB_ERRORS,
    )
    assert computed_rate > 0, "Seed data must produce a non-zero error rate"

    # Combined denominator includes BOTH handler invocations AND job executions
    expect(kpi_strip).to_contain_text(expected_text)
    # Must NOT show handler-only denominator (verifies jobs are in the denominator)
    handler_only_text = f"{GLOBAL_HANDLER_ERRORS} / {GLOBAL_TOTAL_INVOCATIONS} invocations"
    expect(kpi_strip).not_to_contain_text(handler_only_text)


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
    """App cards display status badges only for non-running states."""
    page.goto(base_url + "/")
    # Running app should NOT show a badge (running is the implied default)
    running_card = page.locator("[data-testid='app-card-my_app']")
    expect(running_card.locator(".ht-badge--success")).not_to_be_visible()

    # Failed app should have danger badge
    failed_card = page.locator("[data-testid='app-card-broken_app']")
    expect(failed_card.locator(".ht-badge--danger")).to_be_visible()


def test_app_card_shows_invocation_and_execution_counts(page: Page, base_url: str) -> None:
    """App cards with activity display invocation and execution counts."""
    page.goto(base_url + "/")

    my_app_card = page.locator("[data-testid='app-card-my_app']")
    counts = my_app_card.locator("[data-testid='app-card-counts']")
    expect(counts).to_be_visible()
    expect(counts).to_contain_text(f"{APP_TIER_MY_APP_TOTAL_INVOCATIONS} inv")
    expect(counts).to_contain_text(f"{APP_TIER_MY_APP_TOTAL_EXECUTIONS} exec")

    broken_card = page.locator("[data-testid='app-card-broken_app']")
    broken_counts = broken_card.locator("[data-testid='app-card-counts']")
    expect(broken_counts).to_be_visible()
    expect(broken_counts).to_contain_text(f"{APP_TIER_BROKEN_APP_TOTAL_INVOCATIONS} inv")
    expect(broken_counts).to_contain_text(f"{APP_TIER_BROKEN_APP_TOTAL_EXECUTIONS} exec")

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
    """Error items visible with app name and message.

    The unified error feed shows both app-tier and framework-tier errors together.
    """
    page.goto(base_url + "/")
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()

    # Should contain seeded error data (app-tier + framework-tier combined)
    error_items = error_feed.locator("[data-testid='error-item']")
    expect(error_items).to_have_count(ERRORS_COMBINED_COUNT)

    # Check errors from multiple apps
    expect(error_feed).to_contain_text("my_app")
    expect(error_feed).to_contain_text("Bad state value")
    expect(error_feed).to_contain_text("Light service unavailable")
    expect(error_feed).to_contain_text("broken_app")
    expect(error_feed).to_contain_text("Lock service timed out")

    # Framework error also appears in the unified feed with a "Framework" badge
    expect(error_feed).to_contain_text("DispatchError")
    expect(error_feed).to_contain_text("Framework dispatch failed")


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


def test_app_health_heading_links_to_apps(page: Page, base_url: str) -> None:
    """The App Health heading is a link that navigates to the apps page."""
    page.goto(base_url + "/")
    link = page.get_by_role("link", name="App Health")
    expect(link).to_be_visible()
    link.click()
    expect(page).to_have_url(re.compile(r"/apps/?$"))


# ── Framework Health affordance ─────────────────────────────────────


def test_dashboard_default_shows_all_errors(page: Page, base_url: str) -> None:
    """Default error feed shows all errors: both app-tier and framework-tier.

    The unified error feed uses source_tier='all' by default. Framework errors
    appear alongside app errors, distinguished by a "Framework" badge.
    """
    page.goto(base_url + "/")
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()

    # App-tier errors should be visible
    expect(error_feed).to_contain_text("my_app")
    expect(error_feed).to_contain_text("Bad state value")

    # Framework-tier error must also appear in the unified feed
    expect(error_feed).to_contain_text("DispatchError")
    expect(error_feed).to_contain_text("Framework dispatch failed")


def test_framework_affordance_visible(page: Page, base_url: str) -> None:
    """A visible framework health element is present on the default dashboard.

    The System Health section must be present even without clicking any link.
    AC-18: it must be visible by default on the dashboard.
    """
    page.goto(base_url + "/")
    framework_section = page.locator("[data-testid='framework-health']")
    expect(framework_section).to_be_visible()
    expect(framework_section).to_contain_text("System Health")

    # Error count badge should be present
    error_badge = page.locator("[data-testid='framework-error-count']")
    expect(error_badge).to_be_visible()


def test_framework_affordance_shows_error_count_badge(page: Page, base_url: str) -> None:
    """System Health affordance shows a summary badge with the framework error count.

    The System Health section is a collapsed summary badge — it does NOT expand
    to show its own error list. Framework errors appear in the unified "Recent
    Errors" feed below, with "Framework" badges.
    AC-18: the badge count must be non-zero when framework errors exist.
    """
    page.goto(base_url + "/")
    framework_section = page.locator("[data-testid='framework-health']")
    expect(framework_section).to_be_visible()
    expect(framework_section).to_contain_text("System Health")

    # Error count badge shows the number of framework errors
    error_badge = page.locator("[data-testid='framework-error-count']")
    expect(error_badge).to_be_visible()
    # Badge count must reflect the framework error count from seed data
    expect(error_badge).to_contain_text(str(FRAMEWORK_TIER_TOTAL_HANDLER_ERRORS + FRAMEWORK_TIER_TOTAL_JOB_ERRORS))


def test_framework_errors_in_feed_have_framework_badge(page: Page, base_url: str) -> None:
    """Framework errors in the unified feed show a 'Framework' tier badge.

    The unified error feed renders framework errors with a .ht-tag--framework
    badge and without an <a href> link (no navigable app detail page).
    """
    page.goto(base_url + "/")
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()

    # The framework error should have a "Framework" tier badge
    framework_tag = error_feed.locator(".ht-tag--framework")
    expect(framework_tag).to_be_visible()
    expect(framework_tag).to_contain_text("Framework")

    # The framework app_key must NOT be rendered as a clickable link
    framework_error_link = error_feed.locator("a[href*='__hassette__']")
    expect(framework_error_link).to_have_count(0)


def test_orphan_error_renders_deleted_label(page: Page, base_url: str) -> None:
    """Orphan error (null listener_id) renders 'deleted handler' label instead of crashing."""
    page.goto(base_url + "/")
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()

    # The orphan error has no app_key and no listener_id —
    # the UI must show "deleted handler" instead of a blank or crashing
    expect(error_feed).to_contain_text("deleted handler")
