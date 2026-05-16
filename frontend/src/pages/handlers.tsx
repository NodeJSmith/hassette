import clsx from "clsx";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../hooks/use-filtered-signal-refetch";
import { getAllListeners, getAllJobs } from "../api/endpoints";
import type { ListenerData, JobData } from "../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../hooks/use-media-query";
import { AppLink } from "../components/shared/app-link";
import { Chip } from "../components/shared/chip";
import { EmptyState } from "../components/shared/empty-state";
import { SortHeader, type SortState } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { TableCard } from "../components/shared/table-card";
import { TierToolbar } from "../components/shared/tier-toolbar";
import { formatDurationOrDash, formatRate, pluralize, lastDotSegment } from "../utils/format";
import { useRelativeTime } from "../hooks/use-relative-time";
import styles from "./handlers.module.css";

// ---- Unified row model ----

interface UnifiedRow {
  kind: "listener" | "job";
  id: string;
  app_key: string;
  name: string;
  handler_method: string;
  trigger: string | null;
  runs: number;
  failed: number;
  timed_out: number;
  avg_duration_ms: number;
  next_run_ts: number | null;
  source_tier: string;
}

function listenerToRow(l: ListenerData): UnifiedRow {
  return {
    kind: "listener",
    id: `h-${l.listener_id}`,
    app_key: l.app_key,
    name: lastDotSegment(l.handler_method),
    handler_method: l.handler_method,
    trigger: l.listener_kind,
    runs: l.total_invocations,
    failed: l.failed,
    timed_out: l.timed_out,
    avg_duration_ms: l.avg_duration_ms,
    next_run_ts: null,
    source_tier: l.source_tier,
  };
}

function jobToRow(j: JobData): UnifiedRow {
  return {
    kind: "job",
    id: `j-${j.job_id}`,
    app_key: j.app_key,
    name: j.job_name,
    handler_method: j.handler_method,
    trigger: j.trigger_label || j.trigger_type || null,
    runs: j.total_executions,
    failed: j.failed,
    timed_out: j.timed_out,
    avg_duration_ms: j.avg_duration_ms,
    next_run_ts: j.next_run === null || j.next_run === undefined ? null : j.next_run,
    source_tier: j.source_tier,
  };
}

// ---- Tier filter ----

type TierFilter = "all" | "app" | "framework";

function filterByTier<T extends { source_tier: string }>(items: T[], tier: TierFilter): T[] {
  if (tier === "all") return items;
  return tier === "app"
    ? items.filter((i) => i.source_tier === "app")
    : items.filter((i) => i.source_tier !== "app");
}

// ---- Sort ----

type SortKey = "kind" | "app" | "name" | "trigger" | "runs" | "failed" | "timed_out" | "error_rate" | "avg_duration" | "next_run";

function compareRows(a: UnifiedRow, b: UnifiedRow, sort: SortState<SortKey>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "kind":
      return dir * a.kind.localeCompare(b.kind);
    case "app":
      return dir * a.app_key.localeCompare(b.app_key);
    case "name":
      return dir * a.name.localeCompare(b.name);
    case "trigger":
      return dir * (a.trigger ?? "").localeCompare(b.trigger ?? "");
    case "runs":
      return dir * (a.runs - b.runs);
    case "failed":
      return dir * (a.failed - b.failed);
    case "timed_out":
      return dir * (a.timed_out - b.timed_out);
    case "error_rate": {
      const rateA = a.runs > 0 ? a.failed / a.runs : 0;
      const rateB = b.runs > 0 ? b.failed / b.runs : 0;
      return dir * (rateA - rateB);
    }
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
    case "next_run": {
      const ts = (r: UnifiedRow) => r.next_run_ts ?? Infinity;
      return dir * (ts(a) - ts(b));
    }
    default:
      return 0;
  }
}

// ---- Mobile card ----

interface MobileCardProps {
  href: string;
  appKey: string;
  name: string;
  failing?: boolean;
  "data-testid"?: string;
  metrics: preact.ComponentChildren;
  footer?: preact.ComponentChildren;
}

function MobileCard({ href, appKey, name, failing, metrics, footer, ...rest }: MobileCardProps) {
  return (
    <a href={href} class={clsx(styles.mobileCard, failing && styles.mobileCardFailing)} data-testid={rest["data-testid"]}>
      <div class={styles.mobileCardHeader}>
        <span class="ht-text-mono ht-text-sm">{appKey}</span>
        <span class="ht-text-mono ht-text-sm ht-text-semibold">{name}</span>
      </div>
      <div class={styles.mobileCardMetrics}>{metrics}</div>
      {footer && <div class={styles.mobileCardFooter}>{footer}</div>}
    </a>
  );
}

// ---- Kind indicator ----

// "listener" displays as "event" in the UI — the user-facing term
function KindBadge({ kind }: { kind: "listener" | "job" }) {
  return (
    <Chip variant="muted" size="sm">
      {kind === "listener" ? "event" : "job"}
    </Chip>
  );
}

// ---- Row components (need hooks — cannot be inline map callbacks) ----

interface HandlerRowProps {
  row: UnifiedRow;
}

function HandlerTableRow({ row }: HandlerRowProps) {
  const nextRunRelative = useRelativeTime(row.next_run_ts);
  const errorRate = formatRate(row.failed, row.runs);
  const avgDur = formatDurationOrDash(row.avg_duration_ms);

  const now = Date.now() / 1000;
  const isOverdue = row.next_run_ts !== null && row.next_run_ts < now;
  const nextRunDisplay = row.next_run_ts !== null
    ? (isOverdue ? "overdue" : nextRunRelative)
    : "—";

  return (
    <tr
      class={clsx(styles.row, row.failed > 0 && styles.rowFailing)}
      data-testid={`${row.kind}-row-${row.id}`}
    >
      <td><KindBadge kind={row.kind} /></td>
      <td class="ht-text-mono ht-text-sm">
        <AppLink appKey={row.app_key} />
      </td>
      <td class="ht-text-mono ht-text-sm" title={row.handler_method}>
        <AppLink appKey={row.app_key} handlerId={row.id}>{row.name}</AppLink>
      </td>
      <td class="ht-text-mono ht-text-sm">{row.trigger ?? "—"}</td>
      <td class="ht-text-mono ht-text-sm">{row.runs}</td>
      <td class={`ht-text-mono ht-text-sm${row.failed > 0 ? " ht-text-danger" : ""}`}>
        {row.failed > 0 ? row.failed : "—"}
      </td>
      <td class={`ht-text-mono ht-text-sm${row.timed_out > 0 ? " ht-text-warning" : ""}`}>
        {row.timed_out > 0 ? row.timed_out : "—"}
      </td>
      <td class={`ht-text-mono ht-text-sm${row.failed > 0 ? " ht-text-danger" : ""}`}>
        {errorRate}
      </td>
      <td class="ht-text-mono ht-text-sm">{avgDur}</td>
      <td class={`ht-text-mono ht-text-sm${isOverdue ? " ht-text-warning" : ""}`}>
        {nextRunDisplay}
      </td>
    </tr>
  );
}

function HandlerMobileRow({ row }: HandlerRowProps) {
  const nextRunRelative = useRelativeTime(row.next_run_ts);
  const errorRate = formatRate(row.failed, row.runs);
  const avgDur = formatDurationOrDash(row.avg_duration_ms);

  const now = Date.now() / 1000;
  const isOverdue = row.next_run_ts !== null && row.next_run_ts < now;
  const nextRunDisplay = row.next_run_ts !== null
    ? (isOverdue ? "overdue" : nextRunRelative)
    : null;

  return (
    <MobileCard
      href={`/apps/${row.app_key}/handlers/${row.id}`}
      appKey={row.app_key}
      name={row.name}
      failing={row.failed > 0}
      data-testid={`${row.kind}-row-${row.id}`}
      metrics={<>
        <KindBadge kind={row.kind} />
        {row.trigger && <span>{row.trigger}</span>}
        <span>{row.runs} runs</span>
        {row.failed > 0 && <span class="ht-text-danger">{row.failed} failed</span>}
        {row.timed_out > 0 && <span class="ht-text-warning">{row.timed_out} timed out</span>}
        {row.runs > 0 && <span>{errorRate} err</span>}
        {row.avg_duration_ms > 0 && <span>avg {avgDur}</span>}
      </>}
      footer={row.kind === "job" && nextRunDisplay !== null ? (
        <span class="ht-text-muted">next {nextRunDisplay}</span>
      ) : undefined}
    />
  );
}

// ---- Page ----

export function HandlersPage() {
  useDocumentTitle("Handlers");

  const qp = useQueryParams();

  // Derive state from URL query params; default values omitted from URL
  const tierFilter = (qp.get("tier") ?? "app") as TierFilter;
  const selectedApp = qp.get("app") ?? "";
  const search = qp.get("search") ?? "";
  const sort: SortState<SortKey> = {
    key: (qp.get("sort") ?? "app") as SortKey,
    dir: (qp.get("dir") ?? "asc") as "asc" | "desc",
  };

  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const listenersApi = useScopedApi((since) => getAllListeners(since));
  const jobsApi = useScopedApi((since) => getAllJobs(since));

  const { invocationCompleted, executionCompleted } = useAppState();

  useFilteredSignalRefetch(
    invocationCompleted,
    () => true,
    () => void listenersApi.refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  useFilteredSignalRefetch(
    executionCompleted,
    () => true,
    () => void jobsApi.refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const allListeners = listenersApi.data.value ?? [];
  const allJobs = jobsApi.data.value ?? [];

  const isLoading = (listenersApi.loading.value && allListeners.length === 0)
    || (jobsApi.loading.value && allJobs.length === 0);

  if (isLoading) return <Spinner />;

  // Build unified rows
  const allRows: UnifiedRow[] = [
    ...allListeners.map(listenerToRow),
    ...allJobs.map(jobToRow),
  ];

  // Client-side tier filtering
  const tierFiltered = filterByTier(allRows, tierFilter);

  // Unique app keys for filter dropdown
  const appKeys = [...new Set(tierFiltered.map((r) => r.app_key))].sort();

  // App filter
  const appFiltered = selectedApp
    ? tierFiltered.filter((r) => r.app_key === selectedApp)
    : tierFiltered;

  // Search filter
  const searchLower = search.toLowerCase();
  const filtered = searchLower
    ? appFiltered.filter(
        (r) =>
          r.name.toLowerCase().includes(searchLower) ||
          r.app_key.toLowerCase().includes(searchLower) ||
          (r.trigger ?? "").toLowerCase().includes(searchLower),
      )
    : appFiltered;

  // Sort
  const sorted = [...filtered].sort((a, b) => compareRows(a, b, sort));

  function onSort(s: SortState<SortKey>) {
    qp.set({
      sort: s.key === "app" ? null : s.key,
      dir: s.dir === "asc" ? null : s.dir,
    });
  }

  return (
    <div class="ht-page" data-testid="handlers-page">
      <div class="ht-page-header">
        <h1 class="ht-display">handlers</h1>
      </div>

      <TableCard
        count={<>
          {pluralize(sorted.filter((r) => r.kind === "listener").length, "handler")}
          {" · "}
          {pluralize(sorted.filter((r) => r.kind === "job").length, "job")}
        </>}
        controls={
          <TierToolbar
            tierFilter={tierFilter}
            onTierChange={(v) => qp.set({ tier: v === "app" ? null : v })}
            appKeys={appKeys}
            selectedApp={selectedApp}
            onAppChange={(v) => qp.set({ app: v || null })}
            search={search}
            onSearchChange={(v) => qp.set({ search: v || null })}
            searchPlaceholder="Search..."
            testIdPrefix="handlers"
          />
        }
      >
          {sorted.length === 0 ? (
            <EmptyState title="no handlers found." data-testid="handlers-empty" />
          ) : isMobile ? (
            <div class={styles.mobileCards} data-testid="handlers-table-container">
              {sorted.map((row) => (
                <HandlerMobileRow key={row.id} row={row} />
              ))}
            </div>
          ) : (
            <div data-testid="handlers-table-container">
              <table class={`ht-table ${styles.handlersTable}`}>
                <thead>
                  <tr>
                    <SortHeader sort={sort} onSort={onSort} sortKey="kind">type</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="app">app</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="name">name</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="trigger">trigger</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="runs">runs</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="failed">failed</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="timed_out">timed out</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="error_rate">error rate</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="avg_duration">avg</SortHeader>
                    <SortHeader sort={sort} onSort={onSort} sortKey="next_run">next run</SortHeader>
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
