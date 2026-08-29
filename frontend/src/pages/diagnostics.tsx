import { useQuery } from "@tanstack/react-query";

import type { BootIssue } from "../api/endpoints";
import { getSystemStatus } from "../api/endpoints";
import { BootIssuesPanel } from "../components/diagnostics/boot-issues-panel";
import { LoggingPanel } from "../components/diagnostics/logging-panel";
import { type MergedService, mergeServices } from "../components/diagnostics/merge-services";
import { ServicesPanel } from "../components/diagnostics/services-panel";
import { type TelemetryCounters, TelemetryPanel } from "../components/diagnostics/telemetry-panel";
import { Spinner } from "../components/shared/spinner";
import { StatsStrip, type StatsStripCell } from "../components/shared/stats-strip";
import { useDocumentTitle } from "../hooks/use-document-title";
import { queryKeys } from "../lib/query-keys";
import { useAppStore } from "../state/store";

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

interface DiagnosticsData {
  // Fetch state
  loading: boolean;
  loadError: Error | null;
  // Panel content
  wsConnected: boolean;
  services: MergedService[];
  bootIssues: BootIssue[];
  logQueueDrops: number;
  dbWriteQueueDrops: number;
  logPersistenceInactive: boolean;
  telemetry: TelemetryCounters;
  telemetryDrops: number;
  // Derived visibility — a healthy subsystem renders no panel at all
  showLogging: boolean;
  showTelemetry: boolean;
}

/** Fetches the HTTP status seed, merges the live WS overlay onto it, and derives panel visibility. */
function useDiagnosticsData(): DiagnosticsData {
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

  const logQueueDrops = effectiveSystemStatus?.log_queue_drops ?? 0;
  const dbWriteQueueDrops = effectiveSystemStatus?.db_write_queue_drops ?? 0;
  const logPersistenceInactive = effectiveSystemStatus?.log_persistence_active === false;
  const telemetryDrops = droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures;

  return {
    loading,
    loadError,
    wsConnected: connection === "connected",
    services: mergeServices(effectiveSystemStatus?.services ?? [], serviceStatus),
    bootIssues: effectiveSystemStatus?.boot_issues ?? [],
    logQueueDrops,
    dbWriteQueueDrops,
    logPersistenceInactive,
    showLogging: logQueueDrops > 0 || dbWriteQueueDrops > 0 || logPersistenceInactive,
    telemetry: { droppedOverflow, droppedExhausted, droppedShutdown, errorHandlerFailures, telemetryDegraded },
    telemetryDrops,
    showTelemetry: telemetryDegraded || telemetryDrops > 0,
  };
}

export function DiagnosticsPage() {
  useDocumentTitle("Diagnostics");
  const diag = useDiagnosticsData();

  if (diag.loading) return <Spinner />;

  return (
    <div className="flex flex-1 flex-col gap-8 p-8" data-testid="diagnostics-page">
      <div className="flex items-baseline gap-4 border-b border-[var(--line-1)] pb-3">
        <h1 className="m-0 font-sans text-[length:var(--text-h1)] leading-[var(--text-h1-leading)] tracking-[var(--text-h1-tracking)] text-foreground">
          diagnostics
        </h1>
      </div>

      {diag.loadError ? (
        <div
          className="rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-destructive"
          role="alert"
          data-testid="diag-load-error"
        >
          {diag.loadError.message}
        </div>
      ) : (
        <>
          <StatsStrip
            cells={buildDiagCells(
              diag.services,
              diag.bootIssues.length,
              diag.telemetryDrops,
              diag.logQueueDrops,
              diag.dbWriteQueueDrops,
            )}
            data-testid="diag-stats-strip"
          />

          <ServicesPanel services={diag.services} wsConnected={diag.wsConnected} />

          {diag.bootIssues.length > 0 && <BootIssuesPanel bootIssues={diag.bootIssues} />}

          {diag.showLogging && (
            <LoggingPanel
              logQueueDrops={diag.logQueueDrops}
              dbWriteQueueDrops={diag.dbWriteQueueDrops}
              logPersistenceInactive={diag.logPersistenceInactive}
            />
          )}
        </>
      )}

      {/* Telemetry counters come from the WS stream, not the HTTP seed, so they render even
          when the HTTP load failed. Logging health only renders from an available HTTP seed. */}
      {diag.showTelemetry && <TelemetryPanel {...diag.telemetry} />}
    </div>
  );
}
