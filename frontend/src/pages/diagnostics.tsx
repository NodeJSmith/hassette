import { useState } from "preact/hooks";
import clsx from "clsx";
import { EmptyState } from "../components/shared/empty-state";
import { useApi } from "../hooks/use-api";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";
import type { ServiceStatusEntry } from "../state/create-app-state";
import { getSystemStatus } from "../api/endpoints";
import type { BootIssue } from "../api/endpoints";
import type { components } from "../api/generated-types";
import { statusToKind } from "../utils/status";
import { useRelativeTime } from "../hooks/use-relative-time";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";
import cardStyles from "../components/shared/card.module.css";
import styles from "./diagnostics.module.css";

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
}

function DiagServiceRow({ service }: DiagServiceRowProps) {
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const retryAtLabel = useRelativeTime(service.retry_at);
  const isCooling = service.status === "exhausted_cooling";
  const kind = statusToKind(service.status);

  return (
    <li
      class={styles.serviceRow}
      data-testid={`diag-service-row-${service.resource_name}`}
    >
      <div class={styles.serviceMain}>
        <StatusShape kind={kind} size={10} />
        <span class={`${styles.serviceName} ht-text-mono`}>{service.resource_name}</span>
        <span
          class={`${styles.serviceStatus} ht-text-mono`}
          data-testid={`diag-service-status-${service.resource_name}`}
        >
          {service.status}
        </span>
        {service.ready_phase && (
          <span
            class={styles.servicePhase}
            data-testid={`diag-service-phase-${service.resource_name}`}
          >
            {service.ready_phase}
          </span>
        )}
        {isCooling && service.retry_at !== null && (
          <span
            class={`${styles.serviceRetry} ht-text-mono`}
            data-testid={`diag-service-retry-${service.resource_name}`}
          >
            retry {retryAtLabel}
          </span>
        )}
        {service.exception && (
          <button
            type="button"
            class={styles.exceptionToggle}
            aria-expanded={exceptionOpen}
            onClick={() => setExceptionOpen((v) => !v)}
          >
            {exceptionOpen ? "hide exception" : "show exception"}
          </button>
        )}
      </div>
      {exceptionOpen && service.exception && (
        <pre class={styles.exceptionDetail}>{service.exception}</pre>
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
}

function ServicesPanel({ services, wsConnected }: ServicesPanelProps) {
  return (
    <section
      class={clsx(cardStyles.card, styles.section)}
      aria-label="Internal services"
      data-testid="diag-services-panel"
    >
      <div class={styles.sectionHeader}>
        <h2 class={styles.sectionHeading}>services</h2>
        {!wsConnected && (
          <span class={styles.staleBadge} data-testid="diag-services-stale">
            stale
          </span>
        )}
      </div>
      {services.length === 0 ? (
        <EmptyState title="no services registered." data-testid="diag-services-empty" />
      ) : (
        <ul class={styles.serviceList} aria-label="Service list">
          {services.map((svc) => (
            <DiagServiceRow key={svc.resource_name} service={svc} />
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

const SEVERITY_ORDER: Record<string, number> = { err: 0, warn: 1, info: 2 };

function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  const sorted = [...bootIssues].sort((a, b) =>
    (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99),
  );

  return (
    <section
      class={clsx(cardStyles.card, styles.section)}
      aria-label="Boot issues"
      data-testid="diag-boot-panel"
    >
      <h2 class={styles.sectionHeading}>boot issues</h2>
      {sorted.length === 0 ? (
        <EmptyState icon="✓" title="clean startup — no issues." data-testid="diag-boot-clean" />
      ) : (
        <ul class={styles.bootList} aria-label="Boot issues">
          {sorted.map((issue, i) => {
            const kind = issue.severity === "err" ? "err" : "warn";
            return (
              <li
                key={`${issue.severity}-${issue.label}`}
                class={styles.bootRow}
                data-testid={`diag-boot-issue-${i}`}
              >
                <StatusShape kind={kind} size={10} />
                <div class={styles.bootContent}>
                  <span
                    class={styles.bootLabel}
                    data-testid={`diag-boot-label-${i}`}
                  >
                    {issue.label}
                  </span>
                  <span
                    class={styles.bootDetail}
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
    <li class={styles.dropRow} data-testid={testId}>
      <span class={styles.dropLabel}>{label}</span>
      <span
        class={clsx(styles.dropValue, "ht-text-mono", value > 0 && "ht-text-warning")}
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
      class={clsx(cardStyles.card, styles.section)}
      aria-label="Telemetry health"
      data-testid="diag-telemetry-panel"
    >
      <h2 class={styles.sectionHeading}>telemetry health</h2>
      {telemetryDegraded && (
        <div
          class={styles.degradedBanner}
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
        <ul class={styles.dropList} aria-label="Drop counters">
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
    <div class="ht-page" data-testid="diagnostics-page">
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
