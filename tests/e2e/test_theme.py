"""E2E tests for theme system: dark/light mode, CSS custom properties, persistence."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_dark_mode_is_default(page: Page, base_url: str) -> None:
    """Page loads with data-theme='dark' without any prior interaction."""
    # Clear any stored preference from prior tests.
    page.goto(base_url + "/")
    page.evaluate("localStorage.removeItem('ht-theme')")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_light_mode_toggle_applies_tokens(page: Page, base_url: str) -> None:
    """Switching to light mode changes CSS custom property values."""
    page.goto(base_url + "/")
    page.evaluate("localStorage.removeItem('ht-theme')")
    page.reload()

    # Capture a dark-mode background color token
    dark_bg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ht-bg').trim()")

    # Switch to light
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    light_bg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ht-bg').trim()")

    # The surface color must change between modes — proves the token system works
    assert dark_bg != light_bg, f"Surface color did not change: dark={dark_bg}, light={light_bg}"

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_theme_persistence_survives_reload(page: Page, base_url: str) -> None:
    """Light mode set via toggle persists across a full page reload."""
    page.goto(base_url + "/")
    page.evaluate("localStorage.removeItem('ht-theme')")
    page.reload()

    # Switch to light
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    # Hard reload
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    # Verify localStorage was set
    stored = page.evaluate("localStorage.getItem('ht-theme')")
    assert stored == "light"

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_both_modes_render_without_layout_breakage(page: Page, base_url: str) -> None:
    """Both dark and light mode render the dashboard without layout errors.

    Verifies that key structural elements (sidebar, KPI strip, app grid) remain
    visible after switching modes — catches missing token definitions or broken
    selectors that would hide content.
    """
    page.goto(base_url + "/")
    page.evaluate("localStorage.removeItem('ht-theme')")
    page.reload()

    structural_selectors = [
        ".ht-sidebar",
        "[data-testid='kpi-strip']",
        "#dashboard-app-grid",
    ]

    # Verify in dark mode
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    for selector in structural_selectors:
        expect(page.locator(selector)).to_be_visible()

    # Switch to light and verify again
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    for selector in structural_selectors:
        expect(page.locator(selector)).to_be_visible()

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_theme_toggle_icon_changes(page: Page, base_url: str) -> None:
    """Toggle button shows different icon in dark vs light mode."""
    page.goto(base_url + "/")
    page.evaluate("localStorage.removeItem('ht-theme')")
    page.reload()

    toggle = page.locator('[data-testid="theme-toggle"]')
    dark_html = toggle.inner_html()

    toggle.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    light_html = toggle.inner_html()

    # The toggle should render different content (icon swap)
    assert dark_html != light_html, "Toggle icon did not change between dark and light mode"

    # Clean up
    toggle.click()
