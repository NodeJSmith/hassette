/**
 * Hassette live-updates module.
 *
 * Listens for WebSocket-driven custom events and debounces HTMX
 * partial refreshes for elements annotated with `data-live-refresh`,
 * `data-live-on-app`, or `data-live-on-state` attributes.  Also
 * handles nav active-state updates after boosted navigation.
 *
 * IntersectionObserver tracks element visibility so that off-screen
 * panels skip their refresh until they scroll back into view.
 */
(function () {
  "use strict";

  /**
   * Map of DOM elements awaiting a debounced refresh, keyed by the
   * element itself with the attribute name to re-read at fire time.
   * @type {Map<Element, string>}
   */
  var pendingRefresh = new Map();

  /** @type {ReturnType<typeof setTimeout> | null} Active debounce timer. */
  var refreshTimer = null;

  /** @type {number} Debounce interval in milliseconds. */
  var DEBOUNCE_MS = 500;

  /**
   * Set of currently-visible live-update elements tracked by
   * IntersectionObserver.
   * @type {Set<Element>}
   */
  var visibleElements = new Set();

  /**
   * IntersectionObserver instance that tracks which live-update
   * elements are in the viewport.
   * @type {IntersectionObserver}
   */
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        visibleElements.add(entry.target);
      } else {
        visibleElements.delete(entry.target);
      }
    });
  }, { rootMargin: "100px" });

  /**
   * Start observing a live-update element for visibility.
   * @param {Element} el
   */
  function observe(el) {
    observer.observe(el);
    // Assume initially visible until observer reports otherwise
    visibleElements.add(el);
  }

  // Observe all existing live-update elements on page load
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-live-refresh], [data-live-on-app], [data-live-on-state]").forEach(observe);
  });

  // Re-observe after HTMX page swaps (boosted navigation)
  document.body.addEventListener("htmx:afterSettle", function () {
    document.querySelectorAll("[data-live-refresh], [data-live-on-app], [data-live-on-state]").forEach(function (el) {
      if (!visibleElements.has(el)) {
        observe(el);
      }
    });
  });

  /**
   * Queue an HTMX partial refresh for the given element.
   *
   * If the element is not visible (per IntersectionObserver), the
   * refresh is skipped.  If no debounce timer is running, one is
   * started.  Multiple calls within the debounce window are coalesced.
   *
   * The attribute name is stored instead of the URL so that the URL
   * is re-read at fire time (not enqueue time).  This ensures that
   * Alpine.js x-bind updates to data attributes (e.g. tab filter
   * params) are respected after the debounce window.
   *
   * @param {Element} el   - Target element to swap content into.
   * @param {string}  attr - Attribute name to read the URL from at fire time.
   */
  function scheduleRefresh(el, attr) {
    if (!visibleElements.has(el)) return;
    pendingRefresh.set(el, attr);
    if (!refreshTimer) {
      refreshTimer = setTimeout(function () {
        pendingRefresh.forEach(function (attrName, target) {
          var refreshUrl = target.getAttribute(attrName);
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
      scheduleRefresh(el, "data-live-refresh");
    });
  });

  /* Targeted: on app_status_changed, also refresh [data-live-on-app] elements */
  document.addEventListener("ht:ws-message", function (e) {
    var detail = /** @type {CustomEvent} */ (e).detail;
    if (detail && detail.type === "app_status_changed") {
      document.querySelectorAll("[data-live-on-app]").forEach(function (el) {
        scheduleRefresh(el, "data-live-on-app");
      });
    }
    /* On state_changed, also refresh [data-live-on-state] elements */
    if (detail && detail.type === "state_changed") {
      document.querySelectorAll("[data-live-on-state]").forEach(function (el) {
        scheduleRefresh(el, "data-live-on-state");
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

  /* ── Stats-only poll updater ──────────────────────────────────
   *
   * The hidden #app-handler-stats div is polled every 5s via HTMX.
   * After each swap we read data-* attributes from the polled spans
   * and update the visible handler rows in-place — no DOM replacement,
   * so Alpine.js expand state is preserved.
   */
  document.body.addEventListener("htmx:afterSwap", function (e) {
    var target = /** @type {CustomEvent} */ (e).detail.target;
    if (!target || target.id !== "app-handler-stats") return;

    var spans = target.querySelectorAll("span[data-listener-id]");
    spans.forEach(function (span) {
      var id = span.getAttribute("data-listener-id");
      var total = parseInt(span.getAttribute("data-total-invocations") || "0", 10);
      var failed = parseInt(span.getAttribute("data-failed") || "0", 10);
      var avgMs = parseFloat(span.getAttribute("data-avg-duration-ms") || "0");

      var row = document.getElementById("handler-" + id);
      if (!row) return;

      // Update invocation count text
      var callsEl = row.querySelector(".ht-meta-item[title='Total invocations']");
      if (callsEl) callsEl.textContent = total + " calls";

      // Update or create/remove failed count element
      var statsDiv = row.querySelector(".ht-item-row__stats");
      var failedEl = row.querySelector(".ht-meta-item--strong.ht-text-danger");
      if (failed > 0) {
        if (failedEl) {
          failedEl.textContent = failed + " failed";
        } else if (statsDiv && callsEl) {
          var newFailed = document.createElement("span");
          newFailed.className = "ht-meta-item--strong ht-text-danger";
          newFailed.textContent = failed + " failed";
          callsEl.insertAdjacentElement("afterend", newFailed);
        }
      } else if (failedEl) {
        failedEl.remove();
      }

      // Update or create/remove avg duration element
      // Find the duration span: .ht-meta-item that contains "avg" text
      var durationEl = null;
      var metaItems = row.querySelectorAll(".ht-item-row__stats .ht-meta-item");
      metaItems.forEach(function (el) {
        if (el.textContent.indexOf("avg") !== -1) durationEl = el;
      });
      if (avgMs > 0) {
        var durationText = avgMs.toFixed(1) + "ms avg";
        if (durationEl) {
          durationEl.textContent = durationText;
        } else if (statsDiv) {
          var chevron = row.querySelector(".ht-item-row__chevron");
          var newDuration = document.createElement("span");
          newDuration.className = "ht-meta-item";
          newDuration.textContent = durationText;
          if (chevron) {
            statsDiv.insertBefore(newDuration, chevron);
          } else {
            statsDiv.appendChild(newDuration);
          }
        }
      } else if (durationEl) {
        durationEl.remove();
      }

      // Update status dot: danger if failed > 0, success if total > 0, else neutral
      var dotClass = failed > 0 ? "danger" : total > 0 ? "success" : "neutral";
      var dot = row.querySelector(".ht-item-row__dot");
      if (dot) dot.className = "ht-item-row__dot ht-item-row__dot--" + dotClass;
    });
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
    document.querySelectorAll(".ht-nav-list a").forEach(function (link) {
      var href = norm(link.getAttribute("href") || "");
      var isRoot = href === "/ui";
      var isActive = href === path || (!isRoot && href && path.startsWith(href + "/"));
      link.classList.toggle("is-active", isActive);
    });
  }
  document.body.addEventListener("htmx:pushedIntoHistory", updateNavActive);
  window.addEventListener("popstate", updateNavActive);
})();
