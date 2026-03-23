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
  const { logs } = useAppState();
  const minLevel = useRef(signal("")).current; // "" = All Levels
  const appFilter = useRef(signal("")).current; // "" = All Apps
  const search = useRef(signal("")).current;
  const initialEntries = useRef(signal<LogEntry[]>([])).current;
  const sortAsc = useRef(signal(false)).current;

  // Fetch initial entries on mount
  useEffect(() => {
    getRecentLogs({ app_key: appKey, limit: 200 })
      .then((entries) => { initialEntries.value = entries; })
      .catch(() => { /* API error — initial entries stay empty, WS will still stream */ });
  }, [appKey]);

  // Read version to subscribe to WS updates
  void logs.version.value;

  // Combine initial entries + ring buffer entries
  const wsEntries = logs.toArray().filter((e) => {
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
  const sorted = sortAsc.value ? [...filtered] : [...filtered].reverse();

  return (
    <div class="ht-log-table-container">
      <div class="ht-field-group">
        <div class="ht-select ht-select--sm">
          <select
            value={minLevel.value}
            onChange={(e) => {
              minLevel.value = (e.target as HTMLSelectElement).value;
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
              <th>Level</th>
              <th class="ht-sortable" onClick={() => { sortAsc.value = !sortAsc.value; }}>
                Timestamp {sortAsc.value ? "↑" : "↓"}
              </th>
              {showAppColumn && <th>App</th>}
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={showAppColumn ? 4 : 3} style={{ textAlign: "center" }} class="ht-text-muted">
                  No log entries.
                </td>
              </tr>
            )}
            {sorted.slice(0, 500).map((entry, i) => (
              <tr key={i}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${entry.level === "ERROR" || entry.level === "CRITICAL" ? "danger" : entry.level === "WARNING" ? "warning" : entry.level === "DEBUG" ? "neutral" : "success"}`}>
                    {entry.level}
                  </span>
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(entry.timestamp)}</td>
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
                <td
                  class="ht-log-message"
                  onClick={(e) => { e.currentTarget.classList.toggle("is-expanded"); }}
                >{entry.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
