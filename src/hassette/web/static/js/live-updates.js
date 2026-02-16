/**
 * Hassette live-updates module.
 *
 * Listens for WebSocket-driven custom events and debounces HTMX
 * partial refreshes for elements annotated with `data-live-refresh`,
 * `data-live-on-app`, or `data-live-on-state` attributes.  Also
 * handles nav active-state updates after boosted navigation.
 */
(function () {
  "use strict";

  /**
   * Map of DOM elements awaiting a debounced refresh, keyed by the
   * element itself with the refresh URL as the value.
   * @type {Map<Element, string>}
   */
  var pendingRefresh = new Map();

  /** @type {ReturnType<typeof setTimeout> | null} Active debounce timer. */
  var refreshTimer = null;

  /** @type {number} Debounce interval in milliseconds. */
  var DEBOUNCE_MS = 500;

  /**
   * Queue an HTMX partial refresh for the given element.
   *
   * If no debounce timer is running, one is started.  Multiple calls
   * within the debounce window are coalesced — only the latest URL
   * per element is used when the timer fires.
   *
   * @param {Element} el  - Target element to swap content into.
   * @param {string}  url - URL of the HTMX partial to fetch.
   */
  function scheduleRefresh(el, url) {
    pendingRefresh.set(el, url);
    if (!refreshTimer) {
      refreshTimer = setTimeout(function () {
        pendingRefresh.forEach(function (refreshUrl, target) {
          if (refreshUrl) htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" });
        });
        pendingRefresh.clear();
        refreshTimer = null;
      }, DEBOUNCE_MS);
    }
  }

  /* On any generic refresh event, refresh all [data-live-refresh] elements */
  document.addEventListener("ht:refresh", function () {
    document.querySelectorAll("[data-live-refresh]").forEach(function (el) {
      var url = el.getAttribute("data-live-refresh");
      if (url) scheduleRefresh(el, url);
    });
  });

  /* Targeted: on app_status_changed, also refresh [data-live-on-app] elements */
  document.addEventListener("ht:ws-message", function (e) {
    var detail = /** @type {CustomEvent} */ (e).detail;
    if (detail && detail.type === "app_status_changed") {
      document.querySelectorAll("[data-live-on-app]").forEach(function (el) {
        var url = el.getAttribute("data-live-on-app");
        if (url) scheduleRefresh(el, url);
      });
    }
    /* On state_changed, also refresh [data-live-on-state] elements */
    if (detail && detail.type === "state_changed") {
      document.querySelectorAll("[data-live-on-state]").forEach(function (el) {
        var url = el.getAttribute("data-live-on-state");
        if (url) scheduleRefresh(el, url);
      });
    }
  });

  /* Add pulse animation after HTMX swap for live-updated elements */
  document.body.addEventListener("htmx:afterSwap", function (e) {
    var target = /** @type {CustomEvent} */ (e).detail.target;
    if (
      target &&
      (target.hasAttribute("data-live-refresh") ||
        target.hasAttribute("data-live-on-app") ||
        target.hasAttribute("data-live-on-state"))
    ) {
      target.classList.add("ht-live-pulse");
      setTimeout(function () {
        target.classList.remove("ht-live-pulse");
      }, 600);
    }
  });

  /**
   * Update the `is-active` class on sidebar navigation links to
   * reflect the current URL path.  Called after HTMX boosted
   * navigations and browser back/forward.
   */
  function updateNavActive() {
    /**
     * Normalise a pathname by stripping a trailing slash.
     *
     * @param {string} p - URL pathname.
     * @returns {string} Normalised path.
     */
    function norm(p) { return p && p.length > 1 && p.endsWith("/") ? p.slice(0, -1) : p; }
    var path = norm(window.location.pathname);
    document.querySelectorAll(".menu-list a").forEach(function (link) {
      var href = norm(link.getAttribute("href") || "");
      var isRoot = href === "/ui";
      var isActive = href === path || (!isRoot && href && path.startsWith(href + "/"));
      link.classList.toggle("is-active", isActive);
    });
  }
  document.body.addEventListener("htmx:pushedIntoHistory", updateNavActive);
  window.addEventListener("popstate", updateNavActive);
})();
