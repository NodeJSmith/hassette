/* Hassette live-updates: WS-driven HTMX partial refresh with debounce */
(function () {
  "use strict";

  var pendingRefresh = new Set();
  var refreshTimer = null;
  var DEBOUNCE_MS = 500;

  function scheduleRefresh(el) {
    pendingRefresh.add(el);
    if (!refreshTimer) {
      refreshTimer = setTimeout(function () {
        pendingRefresh.forEach(function (target) {
          var url = target.getAttribute("data-live-refresh");
          if (url) htmx.ajax("GET", url, { target: target, swap: "innerHTML" });
        });
        pendingRefresh.clear();
        refreshTimer = null;
      }, DEBOUNCE_MS);
    }
  }

  /* On any generic refresh event, refresh all [data-live-refresh] elements */
  document.addEventListener("ht:refresh", function () {
    document.querySelectorAll("[data-live-refresh]").forEach(scheduleRefresh);
  });

  /* Targeted: on app_status_changed, also refresh [data-live-on-app] elements */
  document.addEventListener("ht:ws-message", function (e) {
    var detail = e.detail;
    if (detail && detail.type === "app_status_changed") {
      document.querySelectorAll("[data-live-on-app]").forEach(function (el) {
        var url = el.getAttribute("data-live-on-app");
        if (url) {
          el.setAttribute("data-live-refresh", url);
          scheduleRefresh(el);
        }
      });
    }
    /* On state_changed, also refresh [data-live-on-state] elements */
    if (detail && detail.type === "state_changed") {
      document.querySelectorAll("[data-live-on-state]").forEach(function (el) {
        var url = el.getAttribute("data-live-on-state");
        if (url) {
          el.setAttribute("data-live-refresh", url);
          scheduleRefresh(el);
        }
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
