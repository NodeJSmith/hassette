/* Hassette live-updates: WS-driven HTMX partial refresh with debounce */
(function () {
  "use strict";

  var pendingRefresh = new Map();
  var refreshTimer = null;
  var DEBOUNCE_MS = 500;

  function scheduleRefresh(el, url) {
    pendingRefresh.set(el, url);
    if (!refreshTimer) {
      refreshTimer = setTimeout(function () {
        pendingRefresh.forEach(function (refreshUrl, target) {
          if (refreshUrl) htmx.ajax("GET", refreshUrl, { target: target, swap: "innerHTML" });
        });
        pendingRefresh.clear();
        refreshTimer = null;
      }, DEBOUNCE_MS);
    }
  }

  /* On any generic refresh event, refresh all [data-live-refresh] elements */
  document.addEventListener("ht:refresh", function () {
    document.querySelectorAll("[data-live-refresh]").forEach(function (el) {
      scheduleRefresh(el, el.getAttribute("data-live-refresh"));
    });
  });

  /* Targeted: on app_status_changed, also refresh [data-live-on-app] elements */
  document.addEventListener("ht:ws-message", function (e) {
    var detail = e.detail;
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
    var target = e.detail.target;
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
})();
