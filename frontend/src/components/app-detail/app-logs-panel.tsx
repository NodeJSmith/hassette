import { useSignal } from "../../hooks/use-signal";
import { useSubscribe } from "../../hooks/use-subscribe";
import { useLogTable, LogTableView, LogTableWithDrawer } from "../shared/log-table";
import { EmptyState } from "../shared/empty-state";
import { TableCard } from "../shared/table-card";
import { TableFooter } from "../shared/table-footer";

export function AppLogsPanel({ appKey }: { appKey: string }) {
  const search = useSignal("");
  useSubscribe(search);
  const log = useLogTable({ context: "app", appKey, useLocalState: true, search: search.value });

  const searchInput = (
    <input
      type="text"
      class="ht-search"
      placeholder="Search logs…"
      aria-label="Search app logs"
      value={search.value}
      onInput={(e) => { search.value = (e.target as HTMLInputElement).value; }}
      data-testid="app-logs-search"
    />
  );

  const footer = (
    <TableFooter
      count={log.countLabel}
      columnFilters={log.columnFilters}
      onResetFilters={log.hasActiveFilter ? log.resetFilters : undefined}
    />
  );

  return (
    <TableCard search={searchInput} footer={footer} scrollHeight="calc(100vh - 340px)" data-testid="logs-section">
      <LogTableWithDrawer drawerProps={log.drawerProps}>
        {log.isEmpty ? (
          <EmptyState title="no log lines in window" body="nothing has been logged recently." />
        ) : (
          <LogTableView {...log.tableProps} />
        )}
      </LogTableWithDrawer>
    </TableCard>
  );
}
