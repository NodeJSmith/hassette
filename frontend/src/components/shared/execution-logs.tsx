import { Link } from "wouter";

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
    <div data-testid="execution-logs-section">
      <span className="mb-1 block font-mono text-xs uppercase tracking-[var(--text-label-tracking)] text-foreground-faint">
        logs
      </span>
      <TableCard footer={footer}>
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? (
            <p className="m-0 p-3 text-sm text-muted-foreground">no logs for this execution</p>
          ) : (
            <LogTableView {...log.tableProps} />
          )}
        </LogTableWithDrawer>
      </TableCard>
      <p className="mt-2 text-sm">
        <Link href={viewAllHref} data-testid="view-all-logs-link">
          View all logs
        </Link>
      </p>
    </div>
  );
}
