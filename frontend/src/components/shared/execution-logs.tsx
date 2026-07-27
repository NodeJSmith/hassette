import { Link } from "wouter";

import styles from "./execution-logs.module.css";
import { LogTableView, LogTableWithDrawer, useLogTable } from "./log-table";
import { TableCard } from "./table-card";
import { TableFooter } from "./table-footer";

interface Props {
  executionId: string;
}

export function ExecutionLogs({ executionId }: Props) {
  const viewAllHref = `/logs?execution_id=${encodeURIComponent(executionId)}`;
  const log = useLogTable({ context: "execution", executionId, useLocalState: true });

  const footer = (
    <TableFooter
      count={log.countLabel}
      columnFilters={log.columnFilters}
      onResetFilters={log.hasActiveFilter ? log.resetFilters : undefined}
    />
  );

  return (
    <div className={styles.section} data-testid="execution-logs-section">
      <span className={styles.label}>logs</span>
      <TableCard footer={footer}>
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? (
            <p className={styles.emptyInline}>no logs for this execution</p>
          ) : (
            <LogTableView {...log.tableProps} />
          )}
        </LogTableWithDrawer>
      </TableCard>
      <p className={styles.viewAll}>
        <Link href={viewAllHref} data-testid="view-all-logs-link">
          View all logs
        </Link>
      </p>
    </div>
  );
}
