import { useState } from "react";

import { EmptyState } from "../components/shared/empty-state";
import { LogTableView, LogTableWithDrawer, useLogTable } from "../components/shared/log-table";
import { ColumnPicker } from "../components/shared/log-table/column-picker";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useManifests } from "../hooks/use-manifests";
import { useQueryParams } from "../hooks/use-query-params";

const PAGE_CLASS = "flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2";
const PAGE_HEADER_CLASS = "flex items-baseline gap-4 border-b border-border pb-3";
const PAGE_TITLE_CLASS =
  "m-0 font-heading text-[length:var(--text-display)] font-normal tracking-[var(--text-display-tracking)] text-foreground";
const TABLE_SECTION_CLASS = "flex flex-col gap-3";
const SEARCH_INPUT_CLASS =
  "min-w-[var(--size-search-min)] self-end rounded-md border border-[var(--border-strong)] bg-input px-2 py-1.5 font-sans text-[length:var(--text-mono-sm)] text-foreground outline-none placeholder:text-foreground-faint focus-visible:border-primary focus-visible:shadow-[0_0_0_2px_var(--primary-soft)] max-mobile:w-full max-mobile:min-w-0 max-mobile:self-stretch";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { data: manifests = [] } = useManifests();
  const appKeys = manifests.map((m) => m.app_key).sort();
  const qp = useQueryParams();
  const executionId = qp.get("execution_id");

  const [search, setSearch] = useState("");

  const log = useLogTable({
    context: "global",
    appKeys,
    executionId,
    search,
  });

  const searchInput = (
    <input
      type="text"
      className={SEARCH_INPUT_CLASS}
      placeholder="Search logs…"
      aria-label="Search logs"
      value={search}
      onInput={(e) => {
        setSearch((e.target as HTMLInputElement).value);
      }}
      data-testid="logs-search"
    />
  );

  const footerExtras = (
    <>
      {log.livePaused && (
        <button
          type="button"
          className="inline-flex cursor-pointer appearance-none items-center gap-1 rounded-sm border-none bg-transparent px-2 py-[var(--spacing-0-5)] font-sans text-xs font-medium text-[var(--status-warning)] transition-colors hover:bg-[var(--status-warning-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--status-warning)] focus-visible:outline-offset-[var(--spacing-0-5)]"
          onClick={log.resetSort}
          aria-label="Resume live log streaming"
        >
          paused — click to resume
        </button>
      )}
      {!log.isMobile && (
        <ColumnPicker
          selectedColumns={log.columnPickerProps.selectedColumns}
          viewportHidden={log.columnPickerProps.viewportHidden}
          onToggle={log.columnPickerProps.onToggle}
          onReset={log.columnPickerProps.onReset}
        />
      )}
    </>
  );

  const footer = (
    <TableFooter
      count={log.countLabel}
      columnFilters={log.columnFilters}
      onResetFilters={log.hasActiveFilter ? log.resetFilters : undefined}
      extras={footerExtras}
    />
  );

  return (
    <div className={PAGE_CLASS} data-testid="logs-page">
      <div className={PAGE_HEADER_CLASS}>
        <h1 className={PAGE_TITLE_CLASS}>logs</h1>
      </div>
      <div className={TABLE_SECTION_CLASS}>
        {searchInput}
        <TableCard footer={footer} data-testid="logs-card">
          <LogTableWithDrawer drawerProps={log.drawerProps}>
            {log.isEmpty ? (
              <EmptyState
                title="no log lines in window"
                body="nothing has been logged recently. change the level filter or extend the time window to see older lines."
              />
            ) : (
              <LogTableView {...log.tableProps} />
            )}
          </LogTableWithDrawer>
        </TableCard>
      </div>
    </div>
  );
}
