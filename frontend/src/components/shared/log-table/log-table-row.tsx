import clsx from "clsx";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useMemo } from "react";

import type { LogEntry } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { BREAKPOINT_MOBILE, useMediaQuery } from "@/hooks/use-media-query";
import { useRelativeTime } from "@/hooks/use-relative-time";
import { formatTimestamp, truncateId } from "@/utils/format";

import { AppLink } from "../app-link";
import { IconChevron } from "../icons";
import { DETAIL_DRAWER_ID, LEVEL_ABBREV, levelClass } from "./constants";
import { ExecutionIdLink } from "./execution-id-link";
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

  const handleRowClick = (e: ReactMouseEvent) => {
    if (e.target instanceof Element && e.target.closest("a, button")) return;
    onClick();
  };

  return (
    <tr
      key={rowKey}
      className={clsx(styles.row, isSelected && styles.selected)}
      data-level={entry.level}
      onClick={handleRowClick}
      aria-current={isSelected ? "true" : undefined}
    >
      {isColumnVisible("level") && (
        <td className={styles.levelCell}>
          <span className={clsx(styles.levelText, levelClass(styles, "level", entry.level))}>
            {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
          </span>
        </td>
      )}
      {isColumnVisible("timestamp") && (
        <td className={styles.mono}>{isMobile ? relativeTime : formatTimestamp(entry.timestamp)}</td>
      )}
      {isColumnVisible("app") && (
        <td>{entry.app_key ? <AppLink appKey={entry.app_key} /> : <span className={styles.muted}>&mdash;</span>}</td>
      )}
      {isColumnVisible("instance") && (
        <td className={styles.mono} title={entry.instance_name ?? undefined}>
          {entry.instance_name ?? <span className={styles.muted}>&mdash;</span>}
        </td>
      )}
      {isColumnVisible("execution") && (
        <td className={styles.mono}>
          <ExecutionIdLink
            entry={entry}
            linkClassName={styles.execLink}
            mutedClassName={styles.muted}
            title={entry.execution_id ?? undefined}
          >
            {truncateId(entry.execution_id)}
          </ExecutionIdLink>
        </td>
      )}
      {isColumnVisible("function") && (
        <td className={styles.mono}>
          <span className={styles.truncate}>{entry.func_name}()</span>
        </td>
      )}
      {isColumnVisible("module") && (
        <td className={styles.mono}>
          <span className={styles.truncate} title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
            {entry.logger_name.split(".").pop()}:{entry.lineno}
          </span>
        </td>
      )}
      {isColumnVisible("message") && (
        <td className={styles.messageCell} data-testid="log-message-cell">
          {isMobile && !isColumnVisible("app") && entry.func_name && (
            <div className={styles.sourceInline}>
              {entry.app_key ? `${entry.app_key}.` : ""}
              {entry.func_name}()
            </div>
          )}
          <div className={styles.messageText}>{entry.message}</div>
        </td>
      )}
      <td className={styles.detailCell}>
        <Button
          variant="ghost"
          size="icon-xs"
          className={styles.detailBtn}
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
