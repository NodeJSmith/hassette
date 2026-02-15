"""E2E tests for the dev_reload WebSocket handler in ws-handler.js.

Verifies that CSS dev_reload messages hot-swap stylesheets without a page
reload, while JS and template dev_reload messages trigger a full reload.

These tests dispatch a synthetic ``MessageEvent`` on the Alpine WS store's
``_socket`` to simulate a server-pushed dev_reload message.
"""

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_DISPATCH_DEV_RELOAD = """(kind) => {
    var socket = Alpine.store('ws')._socket;
    if (!socket) throw new Error('No WS socket found');
    socket.dispatchEvent(new MessageEvent('message', {
        data: JSON.stringify({ type: "dev_reload", data: { kind: kind, path: "test" } })
    }));
}"""


def test_css_dev_reload_swaps_stylesheet_without_page_reload(page: Page, base_url: str) -> None:
    """CSS dev_reload should update stylesheet href (cache bust) without a full page reload."""
    page.goto(base_url + "/ui/")
    page.wait_for_load_state("networkidle")

    # Set a marker to detect full reload
    page.evaluate("window.__test_marker = true")

    # Dispatch CSS dev_reload
    page.evaluate(_DISPATCH_DEV_RELOAD, "css")

    # Stylesheet href should now contain the cache-busting _r= param
    page.wait_for_function(
        """() => {
            var link = document.querySelector('link[rel="stylesheet"][href*="/ui/static/"]');
            return link && link.href.includes("_r=");
        }""",
        timeout=3000,
    )

    # Page was NOT reloaded — marker survives
    assert page.evaluate("window.__test_marker") is True


def test_js_dev_reload_triggers_full_page_reload(page: Page, base_url: str) -> None:
    """JS dev_reload should trigger location.reload(), destroying transient page state."""
    page.goto(base_url + "/ui/")
    page.wait_for_load_state("networkidle")

    page.evaluate("window.__test_marker = true")

    # Dispatch JS dev_reload — triggers location.reload()
    page.evaluate(_DISPATCH_DEV_RELOAD, "js")

    # After reload, __test_marker should be gone
    page.wait_for_function("typeof window.__test_marker === 'undefined'", timeout=5000)


def test_template_dev_reload_triggers_full_page_reload(page: Page, base_url: str) -> None:
    """Template dev_reload should trigger location.reload(), same as JS."""
    page.goto(base_url + "/ui/")
    page.wait_for_load_state("networkidle")

    page.evaluate("window.__test_marker = true")

    # Dispatch template dev_reload — triggers location.reload()
    page.evaluate(_DISPATCH_DEV_RELOAD, "template")

    page.wait_for_function("typeof window.__test_marker === 'undefined'", timeout=5000)
