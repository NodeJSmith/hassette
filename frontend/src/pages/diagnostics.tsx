import { useState } from "preact/hooks";
import { EmptyState } from "../components/shared/empty-state";
import { useApi } from "../hooks/use-api";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";
import type { ServiceStatusEntry } from "../state/create-app-state";
import { getSystemStatus } from "../api/endpoints";
import type { BootIssue } from "../api/endpoints";
import type { components } from "../api/generated-types";
import { statusToKind } from "../utils/status";
import { formatRelativeTime } from "../utils/format";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];

// ──────────────────────────────────────────────────────────────────────────────
// Merged service entry: HTTP seed + WS live overlay
// ──────────────────────────────────────────────────────────────────────────────

interface MergedService {
  resource_name: string;
  status: string;
  role: string;
  ready_phase: string | null;
  retry_at: number | null;
  exception: string | null;
  /** True when this entry came from a WS update (not just the HTTP seed). */
  from_ws: boolean;
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
      from_ws: false,
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
      from_ws: true,
    });
  }

  return [...merged.values()].sort((a, b) =>
    a.resource_name.localeCompare(b.resource_name),
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Individual service row
// ──────────────────────────────────────────────────────────────────────────────

interface DiagServiceRowProps {
  service: MergedService;
  tick: number;
}

function DiagServiceRow({ service, tick }: DiagServiceRowProps) {
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const isCooling = service.status === "exhausted_cooling";
  const kind = statusToKind(service.status);

  return (
    <li
      class="ht-diag__service-row"
      data-testid={`diag-service-row-${service.resource_name}`}
    >
      <div class="ht-diag__service-main">
        <StatusShape kind={kind} size={10} />
        <span class="ht-diag__service-name ht-text-mono">{service.resource_name}</span>
        <span
          class="ht-diag__service-status ht-text-mono"
          data-testid={`diag-service-status-${service.resource_name}`}
        >
          {service.status}
        </span>
        {service.ready_phase && (
          <span
            class="ht-diag__service-phase"
            data-testid={`diag-service-phase-${service.resource_name}`}
          >
            {service.ready_phase}
          </span>
        )}
        {isCooling && service.retry_at !== null && (
          <span
            class="ht-diag__service-retry ht-text-mono"
            data-testid={`diag-service-retry-${service.resource_name}`}
          >
            {/* tick reference forces re-render on each 30s tick for live relative time */}
            {tick !== undefined && `retry ${formatRelativeTime(service.retry_at)}`}
          </span>
        )}
        {service.exception && (
          <button
            type="button"
            class="ht-diag__exception-toggle"
            aria-expanded={exceptionOpen}
            onClick={() => setExceptionOpen((v) => !v)}
          >
            {exceptionOpen ? "hide exception" : "show exception"}
          </button>
        )}
      </div>
      {exceptionOpen && service.exception && (
        <pre class="ht-diag__exception-detail">{service.exception}</pre>
      )}
    </li>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Services panel
// ──────────────────────────────────────────────────────────────────────────────

interface ServicesPanelProps {
  services: MergedService[];
  wsConnected: boolean;
  tick: number;
}

function ServicesPanel({ services, wsConnected, tick }: ServicesPanelProps) {
  return (
    <section
      class="ht-card ht-diag__section"
      aria-label="Internal services"
      data-testid="diag-services-panel"
    >
      <div class="ht-diag__section-header">
        <h2 class="ht-diag__section-heading">services</h2>
        {!wsConnected && (
          <span class="ht-diag__stale-badge" data-testid="diag-services-stale">
            stale
          </span>
        )}
      </div>
      {services.length === 0 ? (
        <EmptyState title="no services registered." data-testid="diag-services-empty" />
      ) : (
        <ul class="ht-diag__service-list" aria-label="Service list">
          {services.map((svc) => (
            <DiagServiceRow key={svc.resource_name} service={svc} tick={tick} />
          ))}
        </ul>
      )}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Boot issues panel
// ──────────────────────────────────────────────────────────────────────────────

interface BootIssuesPanelProps {
  bootIssues: BootIssue[];
}

function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  // Sort: errors first, then warnings
  const sorted = [...bootIssues].sort((a, b) => {
    if (a.severity === b.severity) return 0;
    return a.severity === "err" ? -1 : 1;
  });

  return (
    <section
      class="ht-card ht-diag__section"
      aria-label="Boot issues"
      data-testid="diag-boot-panel"
    >
      <h2 class="ht-diag__section-heading">boot issues</h2>
      {sorted.length === 0 ? (
        <EmptyState icon="✓" title="clean startup — no issues." data-testid="diag-boot-clean" />
      ) : (
        <ul class="ht-diag__boot-list" aria-label="Boot issues">
          {sorted.map((issue, i) => {
            const kind = issue.severity === "err" ? "err" : "warn";
            return (
              <li
                key={`${issue.severity}-${issue.label}`}
                class="ht-diag__boot-row"
                data-testid={`diag-boot-issue-${i}`}
              >
                <StatusShape kind={kind} size={10} />
                <div class="ht-diag__boot-content">
                  <span
                    class="ht-diag__boot-label"
                    data-testid={`diag-boot-label-${i}`}
                  >
                    {issue.label}
                  </span>
                  <span
                    class="ht-diag__boot-detail"
                    data-testid={`diag-boot-detail-${i}`}
                  >
                    {issue.detail}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Telemetry health panel
// ──────────────────────────────────────────────────────────────────────────────

interface TelemetryPanelProps {
  droppedOverflow: number;
  droppedExhausted: number;
  droppedNoSession: number;
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
    <li class="ht-diag__drop-row" data-testid={testId}>
      <span class="ht-diag__drop-label">{label}</span>
      <span
        class={`ht-diag__drop-value ht-text-mono${value > 0 ? " ht-text-warning" : ""}`}
      >
        {value}
      </span>
    </li>
  );
}

function TelemetryPanel({
  droppedOverflow,
  droppedExhausted,
  droppedNoSession,
  droppedShutdown,
  errorHandlerFailures,
  telemetryDegraded,
}: TelemetryPanelProps) {
  const allZero =
    !telemetryDegraded &&
    droppedOverflow === 0 &&
    droppedExhausted === 0 &&
    droppedNoSession === 0 &&
    droppedShutdown === 0 &&
    errorHandlerFailures === 0;

  return (
    <section
      class="ht-card ht-diag__section"
      aria-label="Telemetry health"
      data-testid="diag-telemetry-panel"
    >
      <h2 class="ht-diag__section-heading">telemetry health</h2>
      {telemetryDegraded && (
        <div
          class="ht-diag__degraded-banner"
          role="alert"
          data-testid="diag-telemetry-degraded"
        >
          Telemetry degraded — writes may be failing or the database is unavailable.
        </div>
      )}
      {allZero ? (
        <p class="ht-text-muted" data-testid="diag-no-drops">
          No telemetry drops.
        </p>
      ) : (
        <ul class="ht-diag__drop-list" aria-label="Drop counters">
          <DropCounterRow
            label="Buffer overflow"
            value={droppedOverflow}
            testId="diag-drop-overflow"
          />
          <DropCounterRow
            label="Write failed"
            value={droppedExhausted}
            testId="diag-drop-exhausted"
          />
          <DropCounterRow
            label="No session"
            value={droppedNoSession}
            testId="diag-drop-no-session"
          />
          <DropCounterRow
            label="During shutdown"
            value={droppedShutdown}
            testId="diag-drop-shutdown"
          />
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

// ──────────────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────────────

export function DiagnosticsPage() {
  useDocumentTitle("Diagnostics");

  const {
    serviceStatus,
    connection,
    tick,
    droppedOverflow,
    droppedExhausted,
    droppedNoSession,
    droppedShutdown,
    errorHandlerFailures,
    telemetryDegraded,
  } = useAppState();

  const { data: systemStatus, loading, error: loadError } = useApi(getSystemStatus);

  const wsConnected = connection.value === "connected";

  // Merge HTTP seed with live WS updates
  const httpServices = systemStatus.value?.services ?? [];
  const mergedServices = mergeServices(httpServices, serviceStatus.value);

  const bootIssues: BootIssue[] = systemStatus.value?.boot_issues ?? [];

  if (loading.value) return <Spinner />;

  return (
    <div class="ht-page ht-diag-page" data-testid="diagnostics-page">
      <div class="ht-page-header">
        <h1 class="ht-display">diagnostics</h1>
      </div>

      {loadError.value ? (
        <div class="ht-alert ht-alert--danger" role="alert" data-testid="diag-load-error">
          {loadError.value}
        </div>
      ) : (
        <>
          <ServicesPanel
            services={mergedServices}
            wsConnected={wsConnected}
            tick={tick.value}
          />

          <BootIssuesPanel bootIssues={bootIssues} />
        </>
      )}

      <TelemetryPanel
        droppedOverflow={droppedOverflow.value}
        droppedExhausted={droppedExhausted.value}
        droppedNoSession={droppedNoSession.value}
        droppedShutdown={droppedShutdown.value}
        errorHandlerFailures={errorHandlerFailures.value}
        telemetryDegraded={telemetryDegraded.value}
      />
    </div>
  );
}
