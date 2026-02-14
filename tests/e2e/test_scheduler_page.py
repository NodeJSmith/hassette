"""E2E tests for the Scheduler page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_scheduler_page_heading(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    expect(page.locator("body")).to_contain_text("Scheduler")


def test_scheduler_jobs_table_shows_seed_data(page: Page, base_url: str) -> None:
    """Verify the job table renders seed data from conftest (check_lights, morning_routine)."""
    page.goto(base_url + "/ui/scheduler")
    jobs_table = page.locator("#scheduler-jobs")
    expect(jobs_table).to_contain_text("check_lights")
    expect(jobs_table).to_contain_text("morning_routine")


def test_scheduler_jobs_show_trigger_type(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    jobs_table = page.locator("#scheduler-jobs")
    # Seed data uses type("interval", ...) and type("cron", ...) triggers
    expect(jobs_table).to_contain_text("interval")
    expect(jobs_table).to_contain_text("cron")


def test_scheduler_jobs_show_repeat_badges(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    jobs_table = page.locator("#scheduler-jobs")
    # Both seed jobs have repeat=True
    expect(jobs_table.locator("text=repeating").first).to_be_visible()


def test_scheduler_jobs_show_active_status(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    jobs_table = page.locator("#scheduler-jobs")
    # Both seed jobs have cancelled=False
    expect(jobs_table.locator("text=active").first).to_be_visible()


def test_scheduler_execution_history_section(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    expect(page.locator("body")).to_contain_text("Execution History")
    # No execution history in seed data
    expect(page.locator("#scheduler-history")).to_contain_text("No execution history")


def test_scheduler_table_headers(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/scheduler")
    # Job table headers
    for header in ("Name", "App", "Trigger", "Next Run", "Repeat", "Status"):
        expect(page.locator(f"th:has-text('{header}')").first).to_be_visible()
