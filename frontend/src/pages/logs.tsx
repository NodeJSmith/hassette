import { EmptyState } from "../components/shared/empty-state";
import { LogTableView, LogTableWithDrawer, useLogTable } from "../components/shared/log-table";
import { ColumnPicker } from "../components/shared/log-table/column-picker";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useManifests } from "../hooks/use-manifests";
import { useQueryParams } from "../hooks/use-query-params";
import { useSignal } from "../hooks/use-signal";
import { useSubscribe } from "../hooks/use-subscribe";
import styles from "./logs.module.css";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { data: manifests = [] } = useManifests();
  const appKeys = manifests.map((m) => m.app_key).sort();
  const qp = useQueryParams();
  const executionId = qp.get("execution_id");

  const search = useSignal("");
  useSubscribe(search);

  const log = useLogTable({
    context: "global",
    appKeys,
    executionId,
    search: search.value,
  });

  const searchInput = (
    <input
      type="text"
      class="ht-search"
      placeholder="Search logs…"
      aria-label="Search logs"
      value={search.value}
      onInput={(e) => {
        search.value = (e.target as HTMLInputElement).value;
      }}
      data-testid="logs-search"
    />
  );

  const footerExtras = (
    <>
      {log.livePaused && (
        <button type="button" class={styles.pausedBtn} onClick={log.resetSort} aria-label="Resume live log streaming">
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
    <div class="ht-page" data-testid="logs-page">
      <div class="ht-page-header">
        <h1 class="ht-display">logs</h1>
      </div>
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
  );
}
