import { useQuery } from "@tanstack/preact-query";
import clsx from "clsx";
import { useState } from "preact/hooks";

import type { BootIssue } from "../api/endpoints";
import { getSystemStatus } from "../api/endpoints";
import type { components } from "../api/generated-types";
import cardStyles from "../components/shared/card.module.css";
import { EmptyState } from "../components/shared/empty-state";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useRelativeTime } from "../hooks/use-relative-time";
import { queryKeys } from "../lib/query-keys";
import { useAppState } from "../state/context";
import type { ServiceStatusEntry } from "../state/create-app-state";
import { statusToKind } from "../utils/status";
import styles from "./diagnostics.module.css";

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];
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

  return [...merged.values()].sort((a, b) => a.resource_name.localeCompare(b.resource_name));
}

interface DiagServiceRowProps {
  service: MergedService;
}

function DiagServiceRow({ service }: DiagServiceRowProps) {
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const retryAtLabel = useRelativeTime(service.retry_at);
  const isCooling = service.status === "exhausted_cooling";
  const kind = statusToKind(service.status);

  return (
    <li class={styles.serviceRow} data-testid={`diag-service-row-${service.resource_name}`}>
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
          <span class={styles.servicePhase} data-testid={`diag-service-phase-${service.resource_name}`}>
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
      {exceptionOpen && service.exception && <pre class={styles.exceptionDetail}>{service.exception}</pre>}
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

interface BootIssuesPanelProps {
  bootIssues: BootIssue[];
}

const SEVERITY_ORDER: Record<string, number> = { err: 0, warn: 1, info: 2 };
const UNKNOWN_SEVERITY_SORT_ORDER = 99;

function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  const sorted = [...bootIssues].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER) -
      (SEVERITY_ORDER[b.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER),
  );

  return (
    <section class={clsx(cardStyles.card, styles.section)} aria-label="Boot issues" data-testid="diag-boot-panel">
      <h2 class={styles.sectionHeading}>boot issues</h2>
      {sorted.length === 0 ? (
        <EmptyState icon="✓" title="clean startup — no issues." data-testid="diag-boot-clean" />
      ) : (
        <ul class={styles.bootList} aria-label="Boot issues">
          {sorted.map((issue, i) => {
            const kind = issue.severity === "err" ? "err" : "warn";
            return (
              <li
                key={`${i}-${issue.severity}-${issue.label}`}
                class={styles.bootRow}
                data-testid={`diag-boot-issue-${i}`}
              >
                <StatusShape kind={kind} size={10} />
                <div class={styles.bootContent}>
                  <span class={styles.bootLabel} data-testid={`diag-boot-label-${i}`}>
                    {issue.label}
                  </span>
                  <span class={styles.bootDetail} data-testid={`diag-boot-detail-${i}`}>
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
    <li class={styles.dropRow} data-testid={testId}>
      <span class={styles.dropLabel}>{label}</span>
      <span class={clsx(styles.dropValue, "ht-text-mono", value > 0 && "ht-text-warning")}>{value}</span>
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
  const allZero =
    !telemetryDegraded &&
    droppedOverflow === 0 &&
    droppedExhausted === 0 &&
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
        <div class={styles.degradedBanner} role="alert" data-testid="diag-telemetry-degraded">
          Telemetry degraded — writes may be failing or the database is unavailable.
        </div>
      )}
      {allZero ? (
        <p class="ht-text-muted" data-testid="diag-no-drops">
          No telemetry drops.
        </p>
      ) : (
        <ul class={styles.dropList} aria-label="Drop counters">
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

  const {
    serviceStatus,
    connection,
    droppedOverflow,
    droppedExhausted,
    droppedShutdown,
    errorHandlerFailures,
    telemetryDegraded,
  } = useAppState();

  const {
    data: systemStatus,
    isPending: loading,
    error: loadError,
  } = useQuery({
    queryKey: queryKeys.systemStatus(),
    queryFn: getSystemStatus,
  });

  const wsConnected = connection.value === "connected";

  // Merge HTTP seed with live WS updates
  const httpServices = systemStatus?.services ?? [];
  const mergedServices = mergeServices(httpServices, serviceStatus.value);

  const bootIssues: BootIssue[] = systemStatus?.boot_issues ?? [];

  if (loading) return <Spinner />;

  return (
    <div class="ht-page" data-testid="diagnostics-page">
      <div class="ht-page-header">
        <h1 class="ht-display">diagnostics</h1>
      </div>

      {loadError ? (
        <div class="ht-alert ht-alert--danger" role="alert" data-testid="diag-load-error">
          {loadError.message}
        </div>
      ) : (
        <>
          <ServicesPanel services={mergedServices} wsConnected={wsConnected} />

          <BootIssuesPanel bootIssues={bootIssues} />
        </>
      )}

      <TelemetryPanel
        droppedOverflow={droppedOverflow.value}
        droppedExhausted={droppedExhausted.value}
        droppedShutdown={droppedShutdown.value}
        errorHandlerFailures={errorHandlerFailures.value}
        telemetryDegraded={telemetryDegraded.value}
      />
    </div>
  );
}
