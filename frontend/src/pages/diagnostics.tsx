import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

// This page applies cardVariants() directly to <section> elements instead of
// using the <Card> component (a <div>). Each panel is a page landmark that
// screen-reader users navigate via aria-label — wrapping it in Card's <div>
// would lose that semantic, so the styling is applied without the element.
import { cardVariants } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { BootIssue } from "../api/endpoints";
import { getSystemStatus } from "../api/endpoints";
import type { components } from "../api/generated-types";
import { EmptyState } from "../components/shared/empty-state";
import { Spinner } from "../components/shared/spinner";
import { StatsStrip, type StatsStripCell } from "../components/shared/stats-strip";
import { StatusShape } from "../components/shared/status-shape";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useRelativeTime } from "../hooks/use-relative-time";
import { queryKeys } from "../lib/query-keys";
import type { ServiceStatusEntry } from "../state/store";
import { useAppStore } from "../state/store";
import { STATUS_DOT_SIZE } from "../utils/constants";
import { statusToKind } from "../utils/status";

const SEVERITY_ORDER: Record<string, number> = { err: 0, warn: 1, info: 2 };
const UNKNOWN_SEVERITY_SORT_ORDER = 99;

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];
type ResourceStatus = components["schemas"]["ResourceStatus"];
interface MergedService {
  resource_name: string;
  status: ResourceStatus;
  role: string;
  ready_phase: string | null;
  retry_at: number | null;
  exception: string | null;
}

function mergeServices(
  httpServices: ServiceInfoResponse[],
  wsStatus: Record<string, ServiceStatusEntry>,
): MergedService[] {
  const merged = new Map<string, MergedService>();

  // Seed from HTTP
  for (const svc of httpServices) {
    merged.set(svc.name, {
      resource_name: svc.name,
      status: svc.status,
      role: svc.role ?? "",
      ready_phase: svc.ready_phase ?? null,
      retry_at: svc.retry_at ?? null,
      exception: null,
    });
  }

  // Overlay with WS updates (live data wins)
  for (const [name, entry] of Object.entries(wsStatus)) {
    merged.set(name, {
      resource_name: name,
      status: entry.status,
      role: entry.role ?? "",
      ready_phase: entry.ready_phase ?? null,
      retry_at: entry.retry_at ?? null,
      exception: entry.exception ?? null,
    });
  }

  // Anomalies first, then alphabetical — a failed service should never hide below the fold.
  return [...merged.values()].sort((a, b) => {
    const anomalyFirst = Number(a.status === "running") - Number(b.status === "running");
    return anomalyFirst || a.resource_name.localeCompare(b.resource_name);
  });
}

function buildDiagCells(
  services: MergedService[],
  bootIssueCount: number,
  telemetryDrops: number,
  logQueueDrops: number,
  dbWriteQueueDrops: number,
): StatsStripCell[] {
  const running = services.filter((s) => s.status === "running").length;
  return [
    { label: "services", value: services.length },
    { label: "running", value: running, tone: running === services.length ? "ok" : "warn" },
    { label: "boot issues", value: bootIssueCount, tone: bootIssueCount > 0 ? "err" : undefined },
    { label: "telemetry drops", value: telemetryDrops, tone: telemetryDrops > 0 ? "warn" : undefined },
    { label: "log queue drops", value: logQueueDrops, tone: logQueueDrops > 0 ? "warn" : undefined },
    { label: "DB write drops", value: dbWriteQueueDrops, tone: dbWriteQueueDrops > 0 ? "warn" : undefined },
  ];
}

interface DiagServiceRowProps {
  service: MergedService;
}

function DiagServiceRow({ service }: DiagServiceRowProps) {
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const retryAtLabel = useRelativeTime(service.retry_at);
  const isCooling = service.status === "exhausted_cooling";
  const isRunning = service.status === "running";
  const kind = statusToKind(service.status);
  // Rows with extra content (status text, phase, exception toggle) span the full grid width.
  const spansFullRow = !isRunning || !!service.exception;

  return (
    <li
      className={cn("min-w-0 py-1", spansFullRow && "col-[1/-1]")}
      data-testid={`diag-service-row-${service.resource_name}`}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <StatusShape kind={kind} size={8} />
        <span className="overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[length:var(--text-mono-sm)] font-medium text-foreground">
          {service.resource_name}
        </span>
        {!isRunning && (
          <span
            className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary"
            data-testid={`diag-service-status-${service.resource_name}`}
          >
            {service.status}
          </span>
        )}
        {!isRunning && service.ready_phase && (
          <span
            className="text-sm italic text-muted-foreground"
            data-testid={`diag-service-phase-${service.resource_name}`}
          >
            {service.ready_phase}
          </span>
        )}
        {isCooling && service.retry_at !== null && (
          <span
            className="font-mono text-[length:var(--text-mono-sm)] text-[var(--status-warning)]"
            data-testid={`diag-service-retry-${service.resource_name}`}
          >
            retry {retryAtLabel}
          </span>
        )}
        {service.exception && (
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent p-0 font-inherit text-sm text-muted-foreground underline hover:text-foreground-secondary"
            aria-expanded={exceptionOpen}
            onClick={() => setExceptionOpen((v) => !v)}
          >
            {exceptionOpen ? "hide exception" : "show exception"}
          </button>
        )}
      </div>
      {exceptionOpen && service.exception && (
        <pre className="mt-2 whitespace-pre-wrap break-all rounded-sm bg-muted p-3 font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
          {service.exception}
        </pre>
      )}
    </li>
  );
}

interface ServicesPanelProps {
  services: MergedService[];
  wsConnected: boolean;
}

function ServicesPanel({ services, wsConnected }: ServicesPanelProps) {
  return (
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label="Internal services"
      data-testid="diag-services-panel"
    >
      <div className="flex items-baseline gap-3">
        <h2 className="m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground">
          services
        </h2>
        {!wsConnected && (
          <span
            className="rounded-full border border-[var(--status-warning)] px-2 py-px font-mono text-xs uppercase tracking-[var(--text-label-tracking)] text-[var(--status-warning)]"
            data-testid="diag-services-stale"
          >
            stale
          </span>
        )}
      </div>
      {services.length === 0 ? (
        <EmptyState title="no services registered." data-testid="diag-services-empty" />
      ) : (
        <ul
          className="grid list-none grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-5 gap-y-1 p-0"
          aria-label="Service list"
        >
          {services.map((svc) => (
            <DiagServiceRow key={svc.resource_name} service={svc} />
          ))}
        </ul>
      )}
    </section>
  );
}

interface BootIssuesPanelProps {
  bootIssues: BootIssue[];
}

function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  const sorted = [...bootIssues].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER) -
      (SEVERITY_ORDER[b.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER),
  );

  return (
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label="Boot issues"
      data-testid="diag-boot-panel"
    >
      <h2 className="m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground">
        boot issues
      </h2>
      <ul className="flex list-none flex-col gap-3 p-0" aria-label="Boot issues">
        {sorted.map((issue, i) => {
          const kind = issue.severity === "err" ? "err" : "warn";
          return (
            <li
              key={`${i}-${issue.severity}-${issue.label}`}
              className="flex items-start gap-3"
              data-testid={`diag-boot-issue-${i}`}
            >
              <StatusShape kind={kind} size={STATUS_DOT_SIZE} />
              <div className="flex flex-1 flex-col gap-1">
                <span
                  className="text-[length:var(--text-body)] font-medium text-foreground"
                  data-testid={`diag-boot-label-${i}`}
                >
                  {issue.label}
                </span>
                <span className="text-sm text-foreground-secondary" data-testid={`diag-boot-detail-${i}`}>
                  {issue.detail}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

interface TelemetryPanelProps {
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
  telemetryDegraded: boolean;
}

interface DropCounterRowProps {
  label: string;
  value: number;
  testId: string;
}

function DropCounterRow({ label, value, testId }: DropCounterRowProps) {
  return (
    <li
      className="flex items-center gap-3 border-b border-[var(--border-subtle)] py-2 last:border-b-0"
      data-testid={testId}
    >
      <span className="flex-1 text-sm text-foreground-secondary">{label}</span>
      <span
        className={cn(
          "min-w-[3ch] text-right font-mono text-[length:var(--text-mono-md)] text-foreground-secondary",
          value > 0 && "text-[var(--status-warning)]",
        )}
      >
        {value}
      </span>
    </li>
  );
}

function TelemetryPanel({
  droppedOverflow,
  droppedExhausted,
  droppedShutdown,
  errorHandlerFailures,
  telemetryDegraded,
}: TelemetryPanelProps) {
  return (
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label="Telemetry health"
      data-testid="diag-telemetry-panel"
    >
      <h2 className="m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground">
        telemetry health
      </h2>
      {telemetryDegraded && (
        <div
          className="rounded-sm border border-[var(--status-warning)] bg-[var(--status-warning-bg)] px-4 py-3 text-sm text-[var(--status-warning)]"
          role="alert"
          data-testid="diag-telemetry-degraded"
        >
          Telemetry degraded — writes may be failing or the database is unavailable.
        </div>
      )}
      {droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures > 0 && (
        <ul className="flex list-none flex-col p-0" aria-label="Drop counters">
          <DropCounterRow label="Buffer overflow" value={droppedOverflow} testId="diag-drop-overflow" />
          <DropCounterRow label="Write failed" value={droppedExhausted} testId="diag-drop-exhausted" />
          <DropCounterRow label="During shutdown" value={droppedShutdown} testId="diag-drop-shutdown" />
          <DropCounterRow
            label="Error handler failures"
            value={errorHandlerFailures}
            testId="diag-drop-error-handler"
          />
        </ul>
      )}
    </section>
  );
}

interface LoggingPanelProps {
  logQueueDrops: number;
  dbWriteQueueDrops: number;
  logPersistenceInactive: boolean;
}

/** Log records drop at one of two independent queues; each row names the bound to raise. */
function LoggingPanel({ logQueueDrops, dbWriteQueueDrops, logPersistenceInactive }: LoggingPanelProps) {
  return (
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label="Logging health"
      data-testid="diag-logging-panel"
    >
      <h2 className="m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground">
        logging health
      </h2>
      {logPersistenceInactive && (
        <div
          className="rounded-sm border border-[var(--status-warning)] bg-[var(--status-warning-bg)] px-4 py-3 text-sm text-[var(--status-warning)]"
          role="alert"
          data-testid="diag-log-persistence-inactive"
        >
          Log persistence inactive — log records are not being written to the database, so the DB write drop count below
          has stopped moving.
        </div>
      )}
      <ul className="flex list-none flex-col p-0" aria-label="Log drop counters">
        <DropCounterRow label="Log queue full" value={logQueueDrops} testId="diag-drop-log-queue" />
        <DropCounterRow
          label="DB write queue full/unavailable"
          value={dbWriteQueueDrops}
          testId="diag-drop-db-write-queue"
        />
      </ul>
    </section>
  );
}

export function DiagnosticsPage() {
  useDocumentTitle("Diagnostics");

  const serviceStatus = useAppStore((s) => s.serviceStatus);
  const connection = useAppStore((s) => s.connection);
  const droppedOverflow = useAppStore((s) => s.droppedOverflow);
  const droppedExhausted = useAppStore((s) => s.droppedExhausted);
  const droppedShutdown = useAppStore((s) => s.droppedShutdown);
  const errorHandlerFailures = useAppStore((s) => s.errorHandlerFailures);
  const telemetryDegraded = useAppStore((s) => s.telemetryDegraded);

  const {
    data: systemStatus,
    isPending: loading,
    error: loadError,
  } = useQuery({
    queryKey: queryKeys.systemStatus(),
    queryFn: ({ signal }) => getSystemStatus(signal),
  });
  const effectiveSystemStatus = loadError ? undefined : systemStatus;

  const wsConnected = connection === "connected";

  // Merge HTTP seed with live WS updates
  const httpServices = effectiveSystemStatus?.services ?? [];
  const mergedServices = mergeServices(httpServices, serviceStatus);

  const bootIssues: BootIssue[] = effectiveSystemStatus?.boot_issues ?? [];

  const logQueueDrops = effectiveSystemStatus?.log_queue_drops ?? 0;
  const dbWriteQueueDrops = effectiveSystemStatus?.db_write_queue_drops ?? 0;
  const logPersistenceInactive = effectiveSystemStatus?.log_persistence_active === false;
  const showLogging = logQueueDrops > 0 || dbWriteQueueDrops > 0 || logPersistenceInactive;
  const telemetryDrops = droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures;
  const showTelemetry = telemetryDegraded || telemetryDrops > 0;

  if (loading) return <Spinner />;

  return (
    <div className="flex flex-1 flex-col gap-8 p-8" data-testid="diagnostics-page">
      <div className="flex items-baseline gap-4 border-b border-[var(--line-1)] pb-3">
        <h1 className="m-0 font-sans text-[length:var(--text-h1)] leading-[var(--text-h1-leading)] tracking-[var(--text-h1-tracking)] text-foreground">
          diagnostics
        </h1>
      </div>

      {loadError ? (
        <div
          className="rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-destructive"
          role="alert"
          data-testid="diag-load-error"
        >
          {loadError.message}
        </div>
      ) : (
        <>
          <StatsStrip
            cells={buildDiagCells(mergedServices, bootIssues.length, telemetryDrops, logQueueDrops, dbWriteQueueDrops)}
            data-testid="diag-stats-strip"
          />

          <ServicesPanel services={mergedServices} wsConnected={wsConnected} />

          {bootIssues.length > 0 && <BootIssuesPanel bootIssues={bootIssues} />}

          {showLogging && (
            <LoggingPanel
              logQueueDrops={logQueueDrops}
              dbWriteQueueDrops={dbWriteQueueDrops}
              logPersistenceInactive={logPersistenceInactive}
            />
          )}
        </>
      )}

      {/* Telemetry counters come from the WS stream, not the HTTP seed, so they render even
          when the HTTP load failed. Logging health only renders from an available HTTP seed. */}
      {showTelemetry && (
        <TelemetryPanel
          droppedOverflow={droppedOverflow}
          droppedExhausted={droppedExhausted}
          droppedShutdown={droppedShutdown}
          errorHandlerFailures={errorHandlerFailures}
          telemetryDegraded={telemetryDegraded}
        />
      )}
    </div>
  );
}
