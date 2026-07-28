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
import styles from "./diagnostics.module.css";

const SEVERITY_ORDER: Record<string, number> = { err: 0, warn: 1, info: 2 };
const UNKNOWN_SEVERITY_SORT_ORDER = 99;

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];
interface MergedService {
  resource_name: string;
  status: string;
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

function buildDiagCells(services: MergedService[], bootIssueCount: number, totalDrops: number): StatsStripCell[] {
  const running = services.filter((s) => s.status === "running").length;
  return [
    { label: "services", value: services.length },
    { label: "running", value: running, tone: running === services.length ? "ok" : "warn" },
    { label: "boot issues", value: bootIssueCount, tone: bootIssueCount > 0 ? "err" : undefined },
    { label: "drops", value: totalDrops, tone: totalDrops > 0 ? "warn" : undefined },
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
      className={cn(styles.serviceRow, spansFullRow && styles.serviceRowDetailed)}
      data-testid={`diag-service-row-${service.resource_name}`}
    >
      <div className={styles.serviceMain}>
        <StatusShape kind={kind} size={8} />
        <span className={`${styles.serviceName} ht-text-mono`}>{service.resource_name}</span>
        {!isRunning && (
          <span
            className={`${styles.serviceStatus} ht-text-mono`}
            data-testid={`diag-service-status-${service.resource_name}`}
          >
            {service.status}
          </span>
        )}
        {!isRunning && service.ready_phase && (
          <span className={styles.servicePhase} data-testid={`diag-service-phase-${service.resource_name}`}>
            {service.ready_phase}
          </span>
        )}
        {isCooling && service.retry_at !== null && (
          <span
            className={`${styles.serviceRetry} ht-text-mono`}
            data-testid={`diag-service-retry-${service.resource_name}`}
          >
            retry {retryAtLabel}
          </span>
        )}
        {service.exception && (
          <button
            type="button"
            className={styles.exceptionToggle}
            aria-expanded={exceptionOpen}
            onClick={() => setExceptionOpen((v) => !v)}
          >
            {exceptionOpen ? "hide exception" : "show exception"}
          </button>
        )}
      </div>
      {exceptionOpen && service.exception && <pre className={styles.exceptionDetail}>{service.exception}</pre>}
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
      className={cn(cardVariants({ variant: "default" }), styles.section)}
      aria-label="Internal services"
      data-testid="diag-services-panel"
    >
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionHeading}>services</h2>
        {!wsConnected && (
          <span className={styles.staleBadge} data-testid="diag-services-stale">
            stale
          </span>
        )}
      </div>
      {services.length === 0 ? (
        <EmptyState title="no services registered." data-testid="diag-services-empty" />
      ) : (
        <ul className={styles.serviceGrid} aria-label="Service list">
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
      className={cn(cardVariants({ variant: "default" }), styles.section)}
      aria-label="Boot issues"
      data-testid="diag-boot-panel"
    >
      <h2 className={styles.sectionHeading}>boot issues</h2>
      <ul className={styles.bootList} aria-label="Boot issues">
        {sorted.map((issue, i) => {
          const kind = issue.severity === "err" ? "err" : "warn";
          return (
            <li
              key={`${i}-${issue.severity}-${issue.label}`}
              className={styles.bootRow}
              data-testid={`diag-boot-issue-${i}`}
            >
              <StatusShape kind={kind} size={STATUS_DOT_SIZE} />
              <div className={styles.bootContent}>
                <span className={styles.bootLabel} data-testid={`diag-boot-label-${i}`}>
                  {issue.label}
                </span>
                <span className={styles.bootDetail} data-testid={`diag-boot-detail-${i}`}>
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
    <li className={styles.dropRow} data-testid={testId}>
      <span className={styles.dropLabel}>{label}</span>
      <span className={cn(styles.dropValue, "ht-text-mono", value > 0 && "ht-text-warning")}>{value}</span>
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
      className={cn(cardVariants({ variant: "default" }), styles.section)}
      aria-label="Telemetry health"
      data-testid="diag-telemetry-panel"
    >
      <h2 className={styles.sectionHeading}>telemetry health</h2>
      {telemetryDegraded && (
        <div className={styles.degradedBanner} role="alert" data-testid="diag-telemetry-degraded">
          Telemetry degraded — writes may be failing or the database is unavailable.
        </div>
      )}
      {droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures > 0 && (
        <ul className={styles.dropList} aria-label="Drop counters">
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
    queryFn: getSystemStatus,
  });

  const wsConnected = connection === "connected";

  // Merge HTTP seed with live WS updates
  const httpServices = systemStatus?.services ?? [];
  const mergedServices = mergeServices(httpServices, serviceStatus);

  const bootIssues: BootIssue[] = systemStatus?.boot_issues ?? [];

  const totalDrops = droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures;
  const showTelemetry = telemetryDegraded || totalDrops > 0;

  if (loading) return <Spinner />;

  return (
    <div className="ht-page" data-testid="diagnostics-page">
      <div className="ht-page-header">
        <h1 className="ht-display">diagnostics</h1>
      </div>

      {loadError ? (
        <div className="ht-alert ht-alert--danger" role="alert" data-testid="diag-load-error">
          {loadError.message}
        </div>
      ) : (
        <>
          <StatsStrip
            cells={buildDiagCells(mergedServices, bootIssues.length, totalDrops)}
            data-testid="diag-stats-strip"
          />

          <ServicesPanel services={mergedServices} wsConnected={wsConnected} />

          {bootIssues.length > 0 && <BootIssuesPanel bootIssues={bootIssues} />}
        </>
      )}

      {/* Telemetry counters come from the WS stream, not the HTTP seed,
          so they render even when the HTTP load failed. */}
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
