import clsx from "clsx";
import { useMemo } from "preact/hooks";
import { Link } from "wouter";

import type { LogEntry } from "@/api/endpoints";
import { BREAKPOINT_MOBILE, useMediaQuery } from "@/hooks/use-media-query";
import { useRelativeTime } from "@/hooks/use-relative-time";
import { logEntryExecutionHref } from "@/utils/app-routes";
import { formatTimestamp, truncateId } from "@/utils/format";

import { AppLink } from "../app-link";
import { Button } from "../button";
import { IconChevron } from "../icons";
import { DETAIL_DRAWER_ID, LEVEL_ABBREV, levelClass } from "./constants";
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

  const handleRowClick = (e: MouseEvent) => {
    if (e.target instanceof Element && e.target.closest("a, button")) return;
    onClick();
  };

  return (
    <tr
      key={rowKey}
      class={clsx(styles.row, isSelected && styles.selected)}
      data-level={entry.level}
      onClick={handleRowClick}
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
        <td>{entry.app_key ? <AppLink appKey={entry.app_key} /> : <span class={styles.muted}>&mdash;</span>}</td>
      )}
      {isColumnVisible("instance") && (
        <td class={styles.mono} title={entry.instance_name ?? undefined}>
          {entry.instance_name ?? <span class={styles.muted}>&mdash;</span>}
        </td>
      )}
      {isColumnVisible("execution") && (
        <td class={styles.mono}>
          {(() => {
            const execHref = logEntryExecutionHref(entry);
            return execHref ? (
              <Link href={execHref} class={styles.execLink} title={entry.execution_id ?? undefined}>
                {truncateId(entry.execution_id)}
              </Link>
            ) : (
              <span class={styles.muted} title={entry.execution_id ?? undefined}>
                {truncateId(entry.execution_id)}
              </span>
            );
          })()}
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
        <td class={styles.messageCell} data-testid="log-message-cell">
          {isMobile && !isColumnVisible("app") && entry.func_name && (
            <div class={styles.sourceInline}>
              {entry.app_key ? `${entry.app_key}.` : ""}
              {entry.func_name}()
            </div>
          )}
          <div class={styles.messageText}>{entry.message}</div>
        </td>
      )}
      <td class={styles.detailCell}>
        <Button
          ghost
          icon
          size="xs"
          class={styles.detailBtn}
          onClick={onClick}
          tabIndex={tabIndex}
          data-roving-item
          aria-label="View log detail"
          aria-expanded={isSelected}
          aria-controls={DETAIL_DRAWER_ID}
        >
          <IconChevron open={isSelected} />
        </Button>
      </td>
    </tr>
  );
}
