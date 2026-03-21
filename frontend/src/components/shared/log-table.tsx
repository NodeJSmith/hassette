import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useAppState } from "../../state/context";
import { formatTimestamp } from "../../utils/format";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

interface Props {
  showAppColumn?: boolean;
  appKey?: string;
}

export function LogTable({ showAppColumn = true, appKey }: Props) {
  const { logs } = useAppState();
  const minLevel = useRef(signal("INFO")).current;
  const search = useRef(signal("")).current;
  const initialEntries = useRef(signal<LogEntry[]>([])).current;
  const sortAsc = useRef(signal(false)).current;

  // Fetch initial entries on mount
  useEffect(() => {
    getRecentLogs({ app_key: appKey, limit: 200 }).then((entries) => {
      initialEntries.value = entries;
    });
  }, [appKey]);

  // Send WS subscribe on mount and when level changes
  // This is handled by the parent page or a dedicated hook
  // For now, WS logs come through the global ring buffer

  // Read version to subscribe to updates
  const _version = logs.version.value;

  // Combine initial entries + ring buffer entries
  const wsEntries = logs.buffer.toArray().filter((e) => {
    if (appKey && e.app_key !== appKey) return false;
    return true;
  });

  const allEntries = [...initialEntries.value, ...wsEntries];

  // Apply level filter
  const levelIndex = LEVELS.indexOf(minLevel.value as typeof LEVELS[number]);
  const levelFiltered = allEntries.filter((e) => {
    const entryIndex = LEVELS.indexOf(e.level as typeof LEVELS[number]);
    return entryIndex >= levelIndex;
  });

  // Apply search filter
  const filtered = search.value
    ? levelFiltered.filter((e) =>
        e.message.toLowerCase().includes(search.value.toLowerCase()) ||
        e.logger_name.toLowerCase().includes(search.value.toLowerCase())
      )
    : levelFiltered;

  // Sort
  const sorted = sortAsc.value ? [...filtered] : [...filtered].reverse();

  return (
    <div class="ht-log-table-container">
      <div class="ht-log-filters">
        <select
          class="ht-select ht-select-sm"
          value={minLevel.value}
          onChange={(e) => { minLevel.value = (e.target as HTMLSelectElement).value; }}
        >
          {LEVELS.map((level) => (
            <option key={level} value={level}>{level}</option>
          ))}
        </select>
        <input
          class="ht-input ht-input-sm"
          type="text"
          placeholder="Search logs..."
          value={search.value}
          onInput={(e) => { search.value = (e.target as HTMLInputElement).value; }}
        />
        <span class="ht-text-secondary ht-text-xs">{filtered.length} entries</span>
      </div>
      <div class="ht-log-table-scroll" style={{ maxHeight: "600px", overflow: "auto" }}>
        <table class="ht-table ht-table-compact ht-table-log">
          <thead>
            <tr>
              <th
                class="ht-sortable"
                onClick={() => { sortAsc.value = !sortAsc.value; }}
              >
                Time {sortAsc.value ? "▲" : "▼"}
              </th>
              <th>Level</th>
              {showAppColumn && <th>App</th>}
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 500).map((entry, i) => (
              <tr key={i} class={`ht-log-row ht-log-${entry.level.toLowerCase()}`}>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(entry.timestamp)}</td>
                <td><span class={`ht-log-level ht-log-level-${entry.level.toLowerCase()}`}>{entry.level}</span></td>
                {showAppColumn && <td class="ht-text-secondary ht-text-xs">{entry.app_key ?? "—"}</td>}
                <td class="ht-log-message">{entry.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
