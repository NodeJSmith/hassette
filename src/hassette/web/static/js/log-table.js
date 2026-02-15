/* Hassette Alpine.js log table component */
document.addEventListener("alpine:init", function () {
  Alpine.data("logTable", function (config) {
    var appKey = config.appKey || null;
    var maxEntries = config.limit || 1000;

    return {
      entries: [],
      filters: { level: "", search: "", app: "" },
      sort: { field: "timestamp", dir: "desc" },
      loading: true,
      error: null,
      _listeners: [],

      get filteredEntries() {
        var self = this;
        var result = this.entries;

        if (this.filters.level) {
          var levels = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
          var minLevel = levels[this.filters.level] || 0;
          result = result.filter(function (e) {
            return (levels[e.level] || 0) >= minLevel;
          });
        }

        if (this.filters.app) {
          var appFilter = this.filters.app;
          result = result.filter(function (e) {
            return e.app_key === appFilter;
          });
        }

        if (this.filters.search) {
          var term = this.filters.search.toLowerCase();
          result = result.filter(function (e) {
            return (
              (e.message && e.message.toLowerCase().indexOf(term) !== -1) ||
              (e.app_key && e.app_key.toLowerCase().indexOf(term) !== -1) ||
              (e.logger_name && e.logger_name.toLowerCase().indexOf(term) !== -1)
            );
          });
        }

        var field = self.sort.field;
        var asc = self.sort.dir === "asc";
        result = result.slice().sort(function (a, b) {
          var av = a[field] || "";
          var bv = b[field] || "";
          if (av < bv) return asc ? -1 : 1;
          if (av > bv) return asc ? 1 : -1;
          return 0;
        });

        return result;
      },

      toggleSort(field) {
        if (this.sort.field === field) {
          this.sort.dir = this.sort.dir === "asc" ? "desc" : "asc";
        } else {
          this.sort.field = field;
          this.sort.dir = field === "timestamp" ? "desc" : "asc";
        }
      },

      sortIcon(field) {
        if (this.sort.field !== field) return "fa-sort";
        return this.sort.dir === "asc" ? "fa-sort-up" : "fa-sort-down";
      },

      formatTime(ts) {
        if (!ts) return "\u2014";
        return new Date(ts * 1000).toLocaleTimeString();
      },

      levelClass(level) {
        return "ht-log-" + (level || "info").toLowerCase();
      },

      init() {
        var self = this;
        var params = new URLSearchParams();
        params.set("limit", String(maxEntries));
        if (appKey) params.set("app_key", appKey);

        fetch("/api/logs/recent?" + params.toString())
          .then(function (r) {
            if (!r.ok) throw new Error("Failed to load logs");
            return r.json();
          })
          .then(function (data) {
            self.entries = data;
            self.loading = false;
          })
          .catch(function (err) {
            self.error = err.message || "Failed to load logs";
            self.loading = false;
          });

        // Subscribe to log streaming
        function subscribeLogs() {
          var ws = Alpine.store("ws");
          if (ws && ws.connected) ws.subscribeLogs("DEBUG");
        }

        function onLogEntry(e) {
          var entry = e.detail.data || e.detail;
          // If locked to an app, ignore entries from other apps
          if (appKey && entry.app_key !== appKey) return;
          self.entries.unshift(entry);
          // Trim beyond max
          if (self.entries.length > maxEntries) {
            self.entries.splice(maxEntries);
          }
        }

        subscribeLogs();
        document.addEventListener("ht:ws-connected", subscribeLogs);
        document.addEventListener("ht:log-entry", onLogEntry);

        // Store references for cleanup
        self._listeners = [
          { event: "ht:ws-connected", handler: subscribeLogs },
          { event: "ht:log-entry", handler: onLogEntry },
        ];
      },

      destroy() {
        // Remove event listeners when component is removed from DOM
        this._listeners.forEach(function (ref) {
          document.removeEventListener(ref.event, ref.handler);
        });
        this._listeners = [];
      },
    };
  });
});
