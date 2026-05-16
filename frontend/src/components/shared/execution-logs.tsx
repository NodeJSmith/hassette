import { useLogTable, LogTableView, LogTableWithDrawer } from "./log-table";
import { TableCard } from "./table-card";
import { TableFooter } from "./table-footer";
import { EmptyState } from "./empty-state";
import styles from "./execution-logs.module.css";

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
    <div class={styles.section} data-testid="execution-logs-section">
      <span class={styles.label}>logs</span>
      <TableCard footer={footer}>
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? (
            <EmptyState
              title="no logs for this execution"
              body="this execution did not produce any log output, or logs have been removed by the retention policy."
            />
          ) : (
            <LogTableView {...log.tableProps} />
          )}
        </LogTableWithDrawer>
      </TableCard>
      <p class={styles.viewAll}>
        <a href={viewAllHref} data-testid="view-all-logs-link">View all logs</a>
      </p>
    </div>
  );
}
