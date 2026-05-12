"""E2E tests for theme system: dark/light mode, CSS custom properties, persistence."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# The SPA defaults to "light" theme (see create-app-state.ts: fallback is "light").
DEFAULT_THEME = "light"
TOGGLED_THEME = "dark"


def _clear_theme_pref(page: Page) -> None:
    """Clear theme localStorage so the SPA falls back to the default."""
    page.evaluate("localStorage.removeItem('hassette:theme'); localStorage.removeItem('ht-theme')")
    page.reload()


def test_light_mode_is_default(page: Page, base_url: str) -> None:
    """Page loads with data-theme='light' without any prior interaction."""
    page.goto(base_url + "/")
    _clear_theme_pref(page)
    expect(page.locator("html")).to_have_attribute("data-theme", DEFAULT_THEME)


def test_toggle_switches_to_dark(page: Page, base_url: str) -> None:
    """Clicking the toggle switches from light to dark mode."""
    page.goto(base_url + "/")
    _clear_theme_pref(page)
    expect(page.locator("html")).to_have_attribute("data-theme", DEFAULT_THEME)

    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)

    # Clean up — toggle back to default
    page.locator('[data-testid="theme-toggle"]').click()


def test_toggle_applies_different_tokens(page: Page, base_url: str) -> None:
    """Switching theme changes CSS custom property values."""
    page.goto(base_url + "/")
    _clear_theme_pref(page)

    # Capture the light-mode background color token
    light_bg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg-page').trim()")

    # Switch to dark
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)

    dark_bg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg-page').trim()")

    # The background color must change between modes — proves the token system works
    assert light_bg != dark_bg, f"Surface color did not change: light={light_bg}, dark={dark_bg}"

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_theme_persistence_survives_reload(page: Page, base_url: str) -> None:
    """Dark mode set via toggle persists across a full page reload."""
    page.goto(base_url + "/")
    _clear_theme_pref(page)

    # Switch to dark
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)

    # Hard reload
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)

    # Verify localStorage was set
    stored = page.evaluate("localStorage.getItem('hassette:theme')")
    assert stored == '"dark"'  # JSON-encoded by setStoredValue

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_both_modes_render_without_layout_breakage(page: Page, base_url: str) -> None:
    """Both light and dark mode render the apps page without layout errors.

    Verifies that key structural elements (sidebar, apps page) remain
    visible after switching modes — catches missing token definitions or broken
    selectors that would hide content.
    """
    page.goto(base_url + "/apps")
    _clear_theme_pref(page)

    structural_selectors = [
        "[data-testid='sidebar']",
        "[data-testid='apps-page']",
    ]

    # Verify in light mode (default)
    expect(page.locator("html")).to_have_attribute("data-theme", DEFAULT_THEME)
    for selector in structural_selectors:
        expect(page.locator(selector)).to_be_visible()

    # Switch to dark and verify again
    page.locator('[data-testid="theme-toggle"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)
    for selector in structural_selectors:
        expect(page.locator(selector)).to_be_visible()

    # Clean up
    page.locator('[data-testid="theme-toggle"]').click()


def test_theme_toggle_icon_changes(page: Page, base_url: str) -> None:
    """Toggle button shows different icon in light vs dark mode."""
    page.goto(base_url + "/")
    _clear_theme_pref(page)

    toggle = page.locator('[data-testid="theme-toggle"]')
    light_html = toggle.inner_html()

    toggle.click()
    expect(page.locator("html")).to_have_attribute("data-theme", TOGGLED_THEME)
    dark_html = toggle.inner_html()

    # The toggle should render different content (icon swap)
    assert light_html != dark_html, "Toggle icon did not change between light and dark mode"

    # Clean up
    toggle.click()
