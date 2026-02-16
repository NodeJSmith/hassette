/**
 * Hassette Alpine.js log table component.
 *
 * Registers a `logTable` Alpine component that displays log entries
 * with filtering, sorting, and real-time WebSocket streaming.
 */
document.addEventListener("alpine:init", function () {
  /**
   * @typedef {Object} LogTableConfig
   * @property {string}  [appKey] - Lock the table to a single app's logs.
   * @property {number}  [limit]  - Maximum number of entries to keep in memory (default 1000).
   */

  /**
   * @typedef {Object} LogEntry
   * @property {string}  level       - Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
   * @property {string}  message     - Log message body.
   * @property {string}  app_key     - Originating application key.
   * @property {string}  logger_name - Python logger name.
   * @property {number}  timestamp   - Unix epoch seconds.
   */

  /**
   * Create a logTable Alpine component.
   *
   * @param {LogTableConfig} config - Component configuration.
   * @returns {Object} Alpine component definition.
   */
  Alpine.data("logTable", function (config) {
    var appKey = config.appKey || null;
    var maxEntries = config.limit || 1000;

    return {
      /** @type {LogEntry[]} All log entries held in memory. */
      entries: [],
      /** @type {{ level: string, search: string, app: string }} Active filters. */
      filters: { level: "", search: "", app: "" },
      /** @type {{ field: string, dir: "asc" | "desc" }} Current sort state. */
      sort: { field: "timestamp", dir: "desc" },
      /** @type {boolean} Whether the initial fetch is in progress. */
      loading: true,
      /** @type {string | null} Error message from the initial fetch, if any. */
      error: null,
      /** @type {{ event: string, handler: Function }[]} Registered DOM listeners for cleanup. */
      _listeners: [],

      /**
       * Computed property that returns entries filtered by level, app,
       * and search term, then sorted by the active sort column.
       *
       * @returns {LogEntry[]} Filtered and sorted log entries.
       */
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

      /**
       * Toggle sort direction for the given column, or switch to it
       * with a sensible default direction.
       *
       * @param {string} field - Column key to sort by (e.g. `"timestamp"`, `"level"`).
       */
      toggleSort(field) {
        if (this.sort.field === field) {
          this.sort.dir = this.sort.dir === "asc" ? "desc" : "asc";
        } else {
          this.sort.field = field;
          this.sort.dir = field === "timestamp" ? "desc" : "asc";
        }
      },

      /**
       * Return the Font Awesome sort icon class for the given column.
       *
       * @param {string} field - Column key.
       * @returns {string} CSS class name (`"fa-sort"`, `"fa-sort-up"`, or `"fa-sort-down"`).
       */
      sortIcon(field) {
        if (this.sort.field !== field) return "fa-sort";
        return this.sort.dir === "asc" ? "fa-sort-up" : "fa-sort-down";
      },

      /**
       * Format a Unix timestamp (seconds) as a locale time string.
       *
       * @param {number | null | undefined} ts - Unix epoch seconds, or null/undefined.
       * @returns {string} Formatted time or an em-dash placeholder.
       */
      formatTime(ts) {
        if (ts == null) return "\u2014";
        return new Date(ts * 1000).toLocaleTimeString();
      },

      /**
       * Return a CSS class for the given log level.
       *
       * @param {string} level - Log level string (e.g. `"ERROR"`).
       * @returns {string} CSS class name (e.g. `"ht-log-error"`).
       */
      levelClass(level) {
        return "ht-log-" + (level || "info").toLowerCase();
      },

      /**
       * Lifecycle hook — fetch recent logs from the REST API, then
       * subscribe to real-time log streaming via the WebSocket store.
       */
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

        /**
         * Handle an incoming log entry from the WebSocket.
         *
         * @param {CustomEvent} e - The `ht:log-entry` event.
         */
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

      /**
       * Lifecycle hook — remove all registered DOM event listeners
       * when the component is destroyed.
       */
      destroy() {
        this._listeners.forEach(function (ref) {
          document.removeEventListener(ref.event, ref.handler);
        });
        this._listeners = [];
      },
    };
  });
});
