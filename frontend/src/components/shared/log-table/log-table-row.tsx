import clsx from "clsx";
import type { LogEntry } from "../../../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useRelativeTime } from "../../../hooks/use-relative-time";
import { formatTimestamp } from "../../../utils/format";
import { AppLink } from "../app-link";
import type { ColumnId, RowKey } from "./types";
import { LEVEL_ABBREV } from "./constants";
import styles from "./log-table-row.module.css";

interface Props {
  entry: LogEntry;
  rowKey: RowKey;
  visibleColumns: ColumnId[];
  isSelected: boolean;
  onClick: () => void;
}

export function LogTableRow({ entry, rowKey, visibleColumns, isSelected, onClick }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const relativeTime = useRelativeTime(entry.timestamp);

  const show = (id: ColumnId) => visibleColumns.includes(id);

  return (
    <tr
      key={rowKey}
      class={clsx(styles.row, isSelected && styles.selected)}
      data-level={entry.level}
      onClick={onClick}
      onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      tabIndex={0}
      role="button"
      aria-current={isSelected ? "true" : undefined}
    >
      {show("level") && (
        <td class={styles.levelCell}>
          <span class={clsx(styles.levelText, (styles as Record<string, string>)[`level${entry.level}`])}>
            {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
          </span>
        </td>
      )}
      {show("timestamp") && (
        <td class={styles.mono}>
          {isMobile ? relativeTime : formatTimestamp(entry.timestamp)}
        </td>
      )}
      {show("app") && (
        <td>
          {entry.app_key ? (
            <AppLink appKey={entry.app_key} />
          ) : (
            <span class={styles.muted}>&mdash;</span>
          )}
        </td>
      )}
      {show("instance") && (
        <td class={styles.mono} title={entry.instance_name ?? undefined}>
          {entry.instance_name ?? <span class={styles.muted}>&mdash;</span>}
        </td>
      )}
      {show("execution") && (
        <td class={styles.mono}>
          {entry.execution_id ? (
            <span class={styles.muted} title={entry.execution_id}>{entry.execution_id.slice(0, 8)}&hellip;</span>
          ) : (
            <span class={styles.muted}>&mdash;</span>
          )}
        </td>
      )}
      {show("function") && (
        <td class={styles.mono}>
          <span class={styles.truncate}>{entry.func_name}()</span>
        </td>
      )}
      {show("module") && (
        <td class={styles.mono}>
          <span class={styles.truncate} title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
            {entry.logger_name.split(".").pop()}:{entry.lineno}
          </span>
        </td>
      )}
      {show("message") && (
        <td class={styles.messageCell}>
          {isMobile && !show("app") && entry.func_name && (
            <div class={styles.sourceInline}>
              {entry.app_key ? `${entry.app_key}.` : ""}{entry.func_name}()
            </div>
          )}
          <div class={styles.messageText}>{entry.message}</div>
        </td>
      )}
    </tr>
  );
}
