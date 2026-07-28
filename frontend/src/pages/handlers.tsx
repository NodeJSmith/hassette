import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { getAllJobs, getAllListeners } from "../api/endpoints";
import { EmptyState } from "../components/shared/empty-state";
import { ARIA_SORT_FOR_DIRECTION, SortHeader, type SortState } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { type ColumnFilters } from "../components/shared/table-types";
import { useDocumentTitle } from "../hooks/use-document-title";
import { BREAKPOINT_SIDEBAR, useMediaQuery } from "../hooks/use-media-query";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import { useAppStore } from "../state/store";
import { pluralize } from "../utils/format";
import { compareHandlerRows, type HandlerSortKey, jobToRow, listenerToRow } from "../utils/handler-rows";
import { HandlerMobileRow, HandlerTableRow } from "./handlers-rows";

const VALID_SORT_KEYS: ReadonlySet<string> = new Set<HandlerSortKey>([
  "kind",
  "app",
  "name",
  "trigger",
  "runs",
  "failed",
  "timed_out",
  "cancelled",
  "error_rate",
  "avg_duration",
  "next_run",
]);
const PAGE_CLASS = "flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2";
const PAGE_HEADER_CLASS = "flex items-baseline gap-4 border-b border-border pb-3";
const PAGE_TITLE_CLASS =
  "m-0 font-heading text-[length:var(--text-display)] font-normal tracking-[var(--text-display-tracking)] text-foreground";
const TABLE_SECTION_CLASS = "flex flex-col gap-3";
const SEARCH_INPUT_CLASS =
  "min-w-[var(--size-search-min)] self-end rounded-md border border-[var(--border-strong)] bg-input px-2 py-1.5 font-sans text-[length:var(--text-mono-sm)] text-foreground outline-none placeholder:text-foreground-faint focus-visible:border-primary focus-visible:shadow-[0_0_0_2px_var(--primary-soft)] max-mobile:w-full max-mobile:min-w-0 max-mobile:self-stretch";
const ALERT_CLASS =
  "flex items-start gap-3 rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-foreground";
const DATA_TABLE_CLASS =
  "w-full table-fixed border-collapse bg-card [&_thead_tr]:bg-muted [&_th]:border-b [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-mono [&_th]:text-xs [&_th]:font-medium [&_th]:uppercase [&_th]:tracking-[var(--text-label-tracking)] [&_th]:text-muted-foreground [&_th]:whitespace-nowrap [&_td]:border-b [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_td]:text-[length:var(--text-small)] [&_td]:overflow-hidden [&_td]:text-ellipsis [&_tbody_tr:last-child_td]:border-b-0 [&_tbody_tr:hover]:bg-muted";

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
  // SortHeader no longer renders the <th> itself (see sort-header.tsx) -- this hand-rolled
  // table owns the <th> element and computes aria-sort the same way log-table-view.tsx does.
  const ariaSortFor = (key: HandlerSortKey) => (sort.key === key ? ARIA_SORT_FOR_DIRECTION[sort.dir] : undefined);

  const isCompact = useMediaQuery(BREAKPOINT_SIDEBAR);

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

  const executionCompleted = useAppStore((s) => s.executionCompleted);

  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.kind === "handler") ?? false,
    queryKeys.allListeners(),
  );
  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.kind === "job") ?? false,
    queryKeys.allJobs(),
  );

  const allListeners = listeners ?? [];
  const allJobs = jobs ?? [];

  const isLoading = (listenersLoading && allListeners.length === 0) || (jobsLoading && allJobs.length === 0);

  if (isLoading) return <Spinner />;

  if (listenersError || jobsError) {
    return (
      <div className={ALERT_CLASS} role="alert">
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

  function handleSort(newSort: SortState<HandlerSortKey>) {
    qp.set({
      sort: newSort.key === "app" ? null : newSort.key,
      dir: newSort.dir === "asc" ? null : newSort.dir,
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
      className={SEARCH_INPUT_CLASS}
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
    <div className={PAGE_CLASS} data-testid="handlers-page">
      <div className={PAGE_HEADER_CLASS}>
        <h1 className={PAGE_TITLE_CLASS}>handlers</h1>
      </div>

      <div className={TABLE_SECTION_CLASS}>
        {searchInput}
        <TableCard footer={footer}>
          {sorted.length === 0 ? (
            <EmptyState title={emptyStateTitle} data-testid="handlers-empty">
              {(selectedApp || search) && (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  clear filters
                </Button>
              )}
            </EmptyState>
          ) : isCompact ? (
            <div className="flex flex-col" data-testid="handlers-table-container">
              {sorted.map((row) => (
                <HandlerMobileRow key={row.id} row={row} />
              ))}
            </div>
          ) : (
            <div data-testid="handlers-table-container">
              <table className={cn(DATA_TABLE_CLASS, "[&_td]:whitespace-nowrap")}>
                <colgroup>
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "18%" }} />
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "8%" }} />
                  <col style={{ width: "8%" }} />
                  <col style={{ width: "7%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" aria-sort={ariaSortFor("kind")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="kind" ariaLabel="type">
                        type
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("app")}>
                      <SortHeader
                        sort={sort}
                        onSort={handleSort}
                        sortKey="app"
                        ariaLabel="app"
                        filterContent={columnFilters.app.content}
                        hasActiveFilter={columnFilters.app.active}
                      >
                        app
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("name")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="name">
                        name
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("trigger")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="trigger">
                        trigger
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("runs")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="runs">
                        runs
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("failed")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="failed">
                        failed
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("timed_out")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="timed_out">
                        timeout
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("cancelled")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="cancelled">
                        cancel
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("error_rate")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="error_rate">
                        err %
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("avg_duration")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="avg_duration">
                        avg
                      </SortHeader>
                    </th>
                    <th scope="col" aria-sort={ariaSortFor("next_run")}>
                      <SortHeader sort={sort} onSort={handleSort} sortKey="next_run">
                        next run
                      </SortHeader>
                    </th>
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
    </div>
  );
}
