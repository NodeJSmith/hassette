import { useState } from "react";

import { EmptyState } from "../shared/empty-state";
import { LogTableView, LogTableWithDrawer, useLogTable } from "../shared/log-table";
import { TableCard } from "../shared/table-card";
import { TableFooter } from "../shared/table-footer";

const SEARCH_INPUT_CLASS =
  "min-w-[var(--size-search-min)] self-end rounded-md border border-[var(--border-strong)] bg-input px-2 py-1.5 font-sans text-[length:var(--text-mono-sm)] text-foreground outline-none placeholder:text-foreground-faint focus-visible:border-primary focus-visible:shadow-[0_0_0_2px_var(--primary-soft)] max-mobile:w-full max-mobile:min-w-0 max-mobile:self-stretch";

export function AppLogsPanel({ appKey }: { appKey: string }) {
  const [search, setSearch] = useState("");
  const log = useLogTable({ context: "app", appKey, useLocalState: true, search });

  const searchInput = (
    <input
      type="text"
      className={SEARCH_INPUT_CLASS}
      placeholder="Search logs…"
      aria-label="Search app logs"
      value={search}
      onInput={(e) => {
        setSearch((e.target as HTMLInputElement).value);
      }}
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
    <>
      {searchInput}
      <TableCard footer={footer} scrollHeight="calc(100vh - 340px)" data-testid="logs-section">
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? (
            <EmptyState title="no log lines in window" body="nothing has been logged recently." />
          ) : (
            <LogTableView {...log.tableProps} />
          )}
        </LogTableWithDrawer>
      </TableCard>
    </>
  );
}
