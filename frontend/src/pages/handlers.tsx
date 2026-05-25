import { getAllJobs, getAllListeners } from "../api/endpoints";
import { Button } from "../components/shared/button";
import { EmptyState } from "../components/shared/empty-state";
import { SortHeader, type SortState } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { type ColumnFilters } from "../components/shared/table-types";
import { useDocumentTitle } from "../hooks/use-document-title";
import { BREAKPOINT_MOBILE, useMediaQuery } from "../hooks/use-media-query";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import { useAppState } from "../state/context";
import { pluralize } from "../utils/format";
import { compareHandlerRows, type HandlerSortKey, jobToRow, listenerToRow } from "../utils/handler-rows";
import styles from "./handlers.module.css";
import { HandlerMobileRow, HandlerTableRow } from "./handlers-rows";

const VALID_SORT_KEYS: ReadonlySet<string> = new Set<HandlerSortKey>([
  "kind",
  "app",
  "name",
  "trigger",
  "runs",
  "failed",
  "timed_out",
  "error_rate",
  "avg_duration",
  "next_run",
]);

export function HandlersPage() {
  useDocumentTitle("Handlers");

  const qp = useQueryParams();

  const selectedApp = qp.get("app") ?? "";
  const search = qp.get("search") ?? "";
  const rawSort = qp.get("sort");
  const sort: SortState<HandlerSortKey> = {
    key: (rawSort !== null && VALID_SORT_KEYS.has(rawSort) ? rawSort : "app") as HandlerSortKey,
    dir: qp.get("dir") === "desc" ? "desc" : "asc",
  };

  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const {
    data: listeners,
    isPending: listenersLoading,
    error: listenersError,
  } = useScopedQuery(queryKeys.allListeners(), (since, signal) => getAllListeners(since, signal));
  const {
    data: jobs,
    isPending: jobsLoading,
    error: jobsError,
  } = useScopedQuery(queryKeys.allJobs(), (since, signal) => getAllJobs(since, signal));

  const { invocationCompleted, executionCompleted } = useAppState();

  useQueryInvalidator(invocationCompleted, () => true, queryKeys.allListeners());
  useQueryInvalidator(executionCompleted, () => true, queryKeys.allJobs());

  const allListeners = listeners ?? [];
  const allJobs = jobs ?? [];

  const isLoading = (listenersLoading && allListeners.length === 0) || (jobsLoading && allJobs.length === 0);

  if (isLoading) return <Spinner />;

  if (listenersError || jobsError) {
    return (
      <div class="ht-alert ht-alert--danger" role="alert">
        {(listenersError ?? jobsError)!.message}
      </div>
    );
  }

  const allRows = [...allListeners.map(listenerToRow), ...allJobs.map(jobToRow)];

  const appRows = allRows.filter((r) => r.source_tier === "app");
  const appKeys = [...new Set(appRows.map((r) => r.app_key))].sort();

  const appFiltered = selectedApp ? appRows.filter((r) => r.app_key === selectedApp) : appRows;

  const searchLower = search.toLowerCase();
  const filtered = searchLower
    ? appFiltered.filter(
        (r) =>
          r.name.toLowerCase().includes(searchLower) ||
          r.app_key.toLowerCase().includes(searchLower) ||
          (r.trigger ?? "").toLowerCase().includes(searchLower),
      )
    : appFiltered;

  const sorted = [...filtered].sort((a, b) => compareHandlerRows(a, b, sort));

  function onSort(s: SortState<HandlerSortKey>) {
    qp.set({
      sort: s.key === "app" ? null : s.key,
      dir: s.dir === "asc" ? null : s.dir,
    });
  }

  const clearFilters = () => qp.set({ app: null, search: null });

  const appFilterContent = (
    <select
      aria-label="Filter by app"
      value={selectedApp}
      onChange={(e) => {
        qp.set({ app: (e.target as HTMLSelectElement).value || null });
      }}
      data-testid="handlers-app-filter"
    >
      <option value="">all apps</option>
      {appKeys.map((key) => (
        <option key={key} value={key}>
          {key}
        </option>
      ))}
    </select>
  );

  const columnFilters: ColumnFilters = {
    app: {
      active: selectedApp !== "",
      label: "App",
      content: appFilterContent,
    },
  };

  const handlerCount = sorted.filter((r) => r.kind === "listener").length;
  const jobCount = sorted.filter((r) => r.kind === "job").length;

  const searchInput = (
    <input
      class="ht-search"
      type="text"
      aria-label="Search handlers"
      placeholder="search handlers…"
      value={search}
      onInput={(e) => {
        qp.set({ search: (e.target as HTMLInputElement).value || null });
      }}
      data-testid="handlers-search"
    />
  );

  const footer = (
    <TableFooter
      count={
        <>
          {pluralize(handlerCount, "handler")}
          {" · "}
          {pluralize(jobCount, "job")}
        </>
      }
      columnFilters={columnFilters}
      onResetFilters={clearFilters}
    />
  );

  function buildEmptyTitle(): string {
    if (selectedApp) return `no handlers found for app: ${selectedApp}.`;
    if (search) return `no handlers match "${search}".`;
    return "no handlers found.";
  }
  const emptyStateTitle = buildEmptyTitle();

  return (
    <div class="ht-page" data-testid="handlers-page">
      <div class="ht-page-header">
        <h1 class="ht-display">handlers</h1>
      </div>

      {searchInput}
      <TableCard footer={footer}>
        {sorted.length === 0 ? (
          <EmptyState title={emptyStateTitle} data-testid="handlers-empty">
            {(selectedApp || search) && (
              <Button ghost size="sm" onClick={clearFilters}>
                clear filters
              </Button>
            )}
          </EmptyState>
        ) : isMobile ? (
          <div class={styles.mobileCards} data-testid="handlers-table-container">
            {sorted.map((row) => (
              <HandlerMobileRow key={row.id} row={row} />
            ))}
          </div>
        ) : (
          <div data-testid="handlers-table-container">
            <table class={`ht-table ht-table--fixed ${styles.handlersTable}`}>
              <colgroup>
                <col style="width: 7%" />
                <col style="width: 13%" />
                <col style="width: 20%" />
                <col style="width: 13%" />
                <col style="width: 7%" />
                <col style="width: 7%" />
                <col style="width: 9%" />
                <col style="width: 9%" />
                <col style="width: 8%" />
                <col style="width: 7%" />
              </colgroup>
              <thead>
                <tr>
                  <SortHeader sort={sort} onSort={onSort} sortKey="kind" ariaLabel="type">
                    type
                  </SortHeader>
                  <SortHeader
                    sort={sort}
                    onSort={onSort}
                    sortKey="app"
                    ariaLabel="app"
                    filterContent={columnFilters.app.content}
                    hasActiveFilter={columnFilters.app.active}
                  >
                    app
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="name">
                    name
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="trigger">
                    trigger
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="runs">
                    runs
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="failed">
                    failed
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="timed_out">
                    timed out
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="error_rate">
                    error rate
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="avg_duration">
                    avg
                  </SortHeader>
                  <SortHeader sort={sort} onSort={onSort} sortKey="next_run">
                    next run
                  </SortHeader>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <HandlerTableRow key={row.id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </TableCard>
    </div>
  );
}
