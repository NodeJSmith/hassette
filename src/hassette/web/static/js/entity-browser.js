/* Hassette Alpine.js entity browser component */
document.addEventListener("alpine:init", function () {
  Alpine.data("entityBrowser", function () {
    return {
      domain: "",
      search: "",
      init() {
        this.refresh();
      },
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
