import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useAppState } from "../../state/context";
import { formatTimestamp, pluralize } from "../../utils/format";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

interface Props {
  showAppColumn?: boolean;
  appKey?: string;
  /** List of app keys for the app filter dropdown (global logs page) */
  appKeys?: string[];
}

export function LogTable({ showAppColumn = true, appKey, appKeys }: Props) {
  const { logs, updateLogSubscription, reconnectVersion } = useAppState();
  const minLevel = useRef(signal("INFO")).current; // default = INFO (matches WS subscription)
  const appFilter = useRef(signal("")).current; // "" = All Apps
  const search = useRef(signal("")).current;
  const initialEntries = useRef(signal<LogEntry[]>([])).current;
  const sortAsc = useRef(signal(false)).current;
  const expandedRows = useRef(signal<Set<string>>(new Set())).current;

  const watermarkRef = useRef(0);

  // Fetch initial entries on mount and after reconnect
  const rv = reconnectVersion.value;
  useEffect(() => {
    watermarkRef.current = 0;
    getRecentLogs({ app_key: appKey, limit: 200 })
      .then((entries) => {
        initialEntries.value = entries;
        watermarkRef.current = entries.reduce((max, e) => Math.max(max, e.seq), 0);
      })
      .catch(() => { /* API error — initial entries stay empty, WS will still stream */ });
  }, [appKey, rv]);

  // Read version to subscribe to WS updates
  void logs.version.value;

  // Combine initial entries + ring buffer entries, deduplicating by seq watermark
  const wsEntries = logs.toArray().filter((e) => {
    if (e.seq <= watermarkRef.current) return false;
    if (appKey && e.app_key !== appKey) return false;
    return true;
  });

  const allEntries = [...initialEntries.value, ...wsEntries];

  // Apply level filter
  const levelFiltered = minLevel.value
    ? allEntries.filter((e) => {
        const levelIndex = LEVELS.indexOf(minLevel.value as (typeof LEVELS)[number]);
        const entryIndex = LEVELS.indexOf(e.level as (typeof LEVELS)[number]);
        return entryIndex >= levelIndex;
      })
    : allEntries; // "" = All Levels — show everything

  // Apply app filter (only for global logs)
  const appFiltered = appFilter.value
    ? levelFiltered.filter((e) => e.app_key === appFilter.value)
    : levelFiltered;

  // Apply search filter
  const filtered = search.value
    ? appFiltered.filter(
        (e) =>
          e.message.toLowerCase().includes(search.value.toLowerCase()) ||
          e.logger_name.toLowerCase().includes(search.value.toLowerCase()),
      )
    : appFiltered;

  // Sort
  const sorted = [...filtered].sort((a, b) =>
    sortAsc.value ? a.timestamp - b.timestamp : b.timestamp - a.timestamp
  );

  return (
    <div class="ht-log-table-container">
      <div class="ht-field-group">
        <div class="ht-select ht-select--sm">
          <select
            data-testid="filter-level"
            value={minLevel.value}
            onChange={(e) => {
              const newLevel = (e.target as HTMLSelectElement).value;
              minLevel.value = newLevel;
              // Update server-side filtering — "" (All Levels) maps to DEBUG
              updateLogSubscription(newLevel || "DEBUG");
            }}
          >
            <option value="">All Levels</option>
            {LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </div>
        {showAppColumn && appKeys && appKeys.length > 0 && (
          <div class="ht-select ht-select--sm">
            <select
              data-testid="filter-app"
              value={appFilter.value}
              onChange={(e) => {
                appFilter.value = (e.target as HTMLSelectElement).value;
              }}
            >
              <option value="">All Apps</option>
              {appKeys.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>
        )}
        <input
          class="ht-input ht-input--sm"
          type="text"
          placeholder="Search..."
          value={search.value}
          onInput={(e) => {
            search.value = (e.target as HTMLInputElement).value;
          }}
        />
        <span class="ht-text-secondary ht-text-xs">{pluralize(filtered.length, "entry", "entries")}</span>
      </div>
      <div class="ht-log-table-scroll" style={{ maxHeight: "600px", overflow: "auto" }}>
        <table class="ht-table ht-table--compact ht-table-log">
          <thead style={{ position: "sticky", top: 0, background: "var(--ht-surface-sticky, var(--ht-bg))" }}>
            <tr>
              <th style={{ width: "90px" }}>Level</th>
              <th style={{ width: "180px" }} aria-sort={sortAsc.value ? "ascending" : "descending"} data-testid="sort-timestamp">
                <button type="button" class="ht-sortable" onClick={() => { sortAsc.value = !sortAsc.value; }}>
                  <span>Timestamp</span>{" "}<span aria-hidden="true">{sortAsc.value ? "↑" : "↓"}</span>
                </button>
              </th>
              {showAppColumn && <th style={{ width: "170px" }}>App</th>}
              <th style={{ width: "220px" }}>Source</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={showAppColumn ? 5 : 4} style={{ textAlign: "center" }} class="ht-text-muted">
                  No log entries.
                </td>
              </tr>
            )}
            {sorted.slice(0, 500).map((entry) => {
              const rowKey = entry.seq ? String(entry.seq) : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
              return (
              <tr key={rowKey}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${entry.level === "ERROR" || entry.level === "CRITICAL" ? "danger" : entry.level === "WARNING" ? "warning" : entry.level === "DEBUG" ? "neutral" : "success"}`}>
                    {entry.level}
                  </span>
                </td>
                <td class="ht-text-mono">{formatTimestamp(entry.timestamp)}</td>
                {showAppColumn && (
                  <td>
                    {entry.app_key ? (
                      <a href={`/apps/${entry.app_key}`} class="ht-text-mono">
                        {entry.app_key}
                      </a>
                    ) : (
                      <span class="ht-text-muted">—</span>
                    )}
                  </td>
                )}
                <td class="ht-text-mono ht-text-xs ht-text-muted" title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
                  {entry.func_name}:{entry.lineno}
                </td>
                <td
                  class="ht-log-message"
                  role="button"
                  tabIndex={0}
                  aria-expanded={expandedRows.value.has(rowKey)}
                  onClick={() => {
                    const next = new Set(expandedRows.value);
                    if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                    expandedRows.value = next;
                  }}
                  onKeyDown={(e: KeyboardEvent) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      const next = new Set(expandedRows.value);
                      if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                      expandedRows.value = next;
                    }
                  }}
                >
                  <div class={`ht-log-message__text${expandedRows.value.has(rowKey) ? " is-expanded" : ""}`}>{entry.message}</div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
