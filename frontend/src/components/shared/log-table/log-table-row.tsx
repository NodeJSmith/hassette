import clsx from "clsx";
import { useMemo } from "preact/hooks";

import type { LogEntry } from "../../../api/endpoints";
import { BREAKPOINT_MOBILE, useMediaQuery } from "../../../hooks/use-media-query";
import { useRelativeTime } from "../../../hooks/use-relative-time";
import { formatTimestamp } from "../../../utils/format";
import { AppLink } from "../app-link";
import { LEVEL_ABBREV, levelClass } from "./constants";
import styles from "./log-table-row.module.css";
import type { ColumnId, RowKey } from "./types";

interface LogTableRowProps {
  entry: LogEntry;
  rowKey: RowKey;
  visibleColumns: ColumnId[];
  isSelected: boolean;
  onClick: () => void;
  tabIndex: 0 | -1;
}

export function LogTableRow({ entry, rowKey, visibleColumns, isSelected, onClick, tabIndex }: LogTableRowProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const relativeTime = useRelativeTime(entry.timestamp);

  const visibleSet = useMemo(() => new Set(visibleColumns), [visibleColumns]);
  const isColumnVisible = (id: ColumnId) => visibleSet.has(id);

  return (
    <tr
      key={rowKey}
      class={clsx(styles.row, isSelected && styles.selected)}
      data-level={entry.level}
      onClick={onClick}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      tabIndex={tabIndex}
      role="button"
      data-roving-item
      aria-current={isSelected ? "true" : undefined}
    >
      {isColumnVisible("level") && (
        <td class={styles.levelCell}>
          <span class={clsx(styles.levelText, levelClass(styles, "level", entry.level))}>
            {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
          </span>
        </td>
      )}
      {isColumnVisible("timestamp") && (
        <td class={styles.mono}>{isMobile ? relativeTime : formatTimestamp(entry.timestamp)}</td>
      )}
      {isColumnVisible("app") && (
        <td>
          {entry.app_key ? (
            <span onClick={(e: MouseEvent) => e.stopPropagation()}>
              <AppLink appKey={entry.app_key} />
            </span>
          ) : (
            <span class={styles.muted}>&mdash;</span>
          )}
        </td>
      )}
      {isColumnVisible("instance") && (
        <td class={styles.mono} title={entry.instance_name ?? undefined}>
          {entry.instance_name ?? <span class={styles.muted}>&mdash;</span>}
        </td>
      )}
      {isColumnVisible("execution") && (
        <td class={styles.mono}>
          {entry.execution_id ? (
            <span class={styles.muted} title={entry.execution_id}>
              {entry.execution_id.slice(0, 8)}&hellip;
            </span>
          ) : (
            <span class={styles.muted}>&mdash;</span>
          )}
        </td>
      )}
      {isColumnVisible("function") && (
        <td class={styles.mono}>
          <span class={styles.truncate}>{entry.func_name}()</span>
        </td>
      )}
      {isColumnVisible("module") && (
        <td class={styles.mono}>
          <span class={styles.truncate} title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
            {entry.logger_name.split(".").pop()}:{entry.lineno}
          </span>
        </td>
      )}
      {isColumnVisible("message") && (
        <td class={styles.messageCell}>
          {isMobile && !isColumnVisible("app") && entry.func_name && (
            <div class={styles.sourceInline}>
              {entry.app_key ? `${entry.app_key}.` : ""}
              {entry.func_name}()
            </div>
          )}
          <div class={styles.messageText}>{entry.message}</div>
        </td>
      )}
    </tr>
  );
}
