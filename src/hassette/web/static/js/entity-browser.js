/**
 * Hassette Alpine.js entity browser component.
 *
 * Registers an `entityBrowser` Alpine component that filters entities
 * by domain and search term, fetching results via HTMX partial swap.
 */
document.addEventListener("alpine:init", function () {
  Alpine.data("entityBrowser", function () {
    return {
      /** @type {string} Selected domain filter (empty = all domains). */
      domain: "",
      /** @type {string} Free-text search filter. */
      search: "",

      /** Fetch the initial entity list on mount. */
      init() {
        this.refresh();
      },

      /**
       * Build a query string from the current filters and swap the
       * entity list partial into `#entity-list` via HTMX.
       */
      refresh() {
        var params = [];
        if (this.domain)
          params.push("domain=" + encodeURIComponent(this.domain));
        if (this.search)
          params.push("search=" + encodeURIComponent(this.search));
        var url =
          "/ui/partials/entity-list" +
          (params.length ? "?" + params.join("&") : "");
        htmx.ajax("GET", url, { target: "#entity-list", swap: "innerHTML" });
      },
    };
  });
});
