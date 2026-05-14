import { useEffect, useRef } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import { useLocation } from "wouter";
import clsx from "clsx";
import type { ListenerData, JobData } from "../../api/endpoints";
import { getHandlerInvocations, getJobExecutions } from "../../api/endpoints";
import { HandlerList, type SelectedHandlerId, listenerStatusKind, jobStatusKind } from "./handler-list";
import { ExecutionTable } from "../shared/execution-table";
import { HandlersHealthStrip } from "./health-strip";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useCorrectUrl } from "../../hooks/use-correct-url";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-filtered-signal-refetch";
import { formatTriggerDetail, formatDurationOrDash, formatOptionalDuration, lastDotSegment, parseSourceLocation } from "../../utils/format";
import { useRelativeTime } from "../../hooks/use-relative-time";

import { handlerKindLabel } from "../../utils/status";
import { BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { EmptyState } from "../shared/empty-state";
import { ErrorBanner } from "../shared/error-banner";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import { Badge } from "../shared/badge";
import { Button } from "../shared/button";
import { Chip } from "../shared/chip";
import styles from "./handlers-tab.module.css";


interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  /** Raw `:handlerId` route parameter, e.g. "h-42" or "j-7". null = no selection. */
  selectedHandler: string | null;
  appKey: string;
  instanceQs: string;
  onSwitchToCode?: (line?: number) => void;
}

/** Inline chips for listener modifier options. */
function ModifierChips({ listener }: { listener: ListenerData }) {
  const chips: Array<{ label: string; value?: string }> = [];
  if (listener.debounce) chips.push({ label: "debounce", value: `${listener.debounce * 1000}ms` }); // backend stores seconds
  if (listener.throttle) chips.push({ label: "throttle", value: `${listener.throttle * 1000}ms` }); // backend stores seconds
  if (listener.once) chips.push({ label: "once" });
  if (listener.priority) chips.push({ label: "priority", value: String(listener.priority) });
  if (listener.immediate) chips.push({ label: "immediate" });
  if (listener.duration) chips.push({ label: "duration", value: `${listener.duration}s` });

  if (chips.length === 0) return null;
  return (
    <div class={styles.chipRow} data-testid="modifier-chips">
      {chips.map((c) => (
        <Chip key={c.label} variant="modifier">
          {c.label}{c.value ? ` ${c.value}` : ""}
        </Chip>
      ))}
    </div>
  );
}

/** Inline chips for job schedule configuration. */
function ScheduleChips({ job }: { job: JobData }) {
  const chips: Array<{ label: string }> = [];

  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  if (chips.length === 0) return null;
  return (
    <div class={styles.chipRow} data-testid="schedule-chips">
      {chips.map((c) => (
        <Chip key={c.label} variant="schedule">{c.label}</Chip>
      ))}
    </div>
  );
}

interface StatsCell {
  label: string;
  value: string | number;
  tone?: "err" | "warn";
}

function DetailStatsRow({ cells, testId }: { cells: StatsCell[]; testId?: string }) {
  return (
    <div class={styles.detailStatsRow} data-testid={testId}>
      {cells.map((cell) => (
        <div
          class={styles.detailStatsCell}
          key={cell.label}
          data-testid={testId ? `${testId}-cell` : undefined}
        >
          <span class={styles.detailStatsLabel}>{cell.label}</span>
          <span
            class={clsx(
              styles.detailStatsValue,
              cell.tone === "err" && styles.detailStatsValueErr,
              cell.tone === "warn" && styles.detailStatsValueWarn,
            )}
            data-tone={cell.tone}
          >
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function handlerStatsCells(listener: ListenerData, lastInvokedLabel: string): StatsCell[] {
  const cells: StatsCell[] = [
    { label: "Calls", value: listener.total_invocations },
    { label: "Successful", value: listener.successful },
    { label: "Last", value: listener.last_invoked_at ? lastInvokedLabel || "—" : "—" },
    { label: "Failed", value: listener.failed > 0 ? listener.failed : "—", tone: listener.failed > 0 ? "err" : undefined },
    { label: "Timed Out", value: listener.timed_out > 0 ? listener.timed_out : "—", tone: listener.timed_out > 0 ? "warn" : undefined },
  ];
  if (listener.cancelled > 0) cells.push({ label: "Cancelled", value: listener.cancelled });
  cells.push(
    { label: "Min", value: formatOptionalDuration(listener.min_duration_ms) },
    { label: "Avg", value: formatDurationOrDash(listener.avg_duration_ms) },
    { label: "Max", value: formatOptionalDuration(listener.max_duration_ms) },
  );
  return cells;
}

function jobStatsCells(job: JobData, lastExecutedLabel: string): StatsCell[] {
  return [
    { label: "Runs", value: job.total_executions },
    { label: "Successful", value: job.successful },
    { label: "Last", value: job.last_executed_at ? lastExecutedLabel || "—" : "—" },
    { label: "Failed", value: job.failed > 0 ? job.failed : "—", tone: job.failed > 0 ? "err" : undefined },
    { label: "Timed Out", value: job.timed_out > 0 ? job.timed_out : "—", tone: job.timed_out > 0 ? "warn" : undefined },
    { label: "Min", value: formatOptionalDuration(job.min_duration_ms) },
    { label: "Avg", value: formatDurationOrDash(job.avg_duration_ms) },
    { label: "Max", value: formatOptionalDuration(job.max_duration_ms) },
  ];
}



interface ListenerDetailProps {
  listener: ListenerData;
  onSwitchToCode?: (line?: number) => void;
}

function ListenerDetail({ listener, onSwitchToCode }: ListenerDetailProps) {
  const { data: invocations, loading, refetch } = useScopedApi(
    (since) => getHandlerInvocations(listener.listener_id, 50, since),
    { deps: [listener.listener_id] },
  );

  const { invocationCompleted } = useAppState();
  const lastInvokedLabel = useRelativeTime(listener.last_invoked_at ?? null);

  // Targeted real-time refetch when a matching invocation_completed event arrives
  useFilteredSignalRefetch(
    invocationCompleted,
    (events) => events?.some((e) => e.listener_id === listener.listener_id) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const kindLabel = handlerKindLabel("listener", listener.listener_kind, null);
  const listenerKind = listenerStatusKind(listener);
  const isFailing = listenerKind === "err";
  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(listener.source_location);

  return (
    <div class={styles.detailPaneWrapper} data-testid={`listener-detail-${listener.listener_id}`}>
    <div class={styles.detailPaneContent}>
      {/* Header: kind badge + name + status pill */}
      <div class={styles.detailPaneHeader}>
        <Chip variant="kind" kind={listenerKind} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={listenerKind} size={8} />
          {kindLabel}
        </Chip>
        <span class={styles.detailPaneHandlerName}>{lastDotSegment(listener.handler_method)}</span>
        {isFailing && (
          <Badge variant="danger" size="sm" data-testid="handler-status-pill">failing</Badge>
        )}
      </div>

      {/* Subtitle: human_description */}
      {listener.human_description && (
        <p class={styles.detailPaneSubtitle} data-testid="handler-human-description">
          {listener.human_description}
        </p>
      )}

      {/* Registration source: actual code snippet */}
      {listener.registration_source && (
        <div class={styles.detailPaneRegistration} data-testid="handler-registration-source">
          <span class="ht-detail-label">Registration</span>
          <pre class={styles.detailPaneCodeSnippet}><code>{listener.registration_source}</code></pre>
        </div>
      )}

      {/* Modifier chips */}
      <ModifierChips listener={listener} />

      {/* Source file location */}
      {listener.source_location && (
        <div class={styles.detailPaneSourceLoc} data-testid="handler-source-location">
          <span class="ht-text-mono ht-text-sm ht-text-muted">
            {sourceFilename}{sourceLine ? `:${sourceLine}` : ""}
          </span>
        </div>
      )}

      {/* Error banner */}
      {isFailing && (listener.last_error_message || listener.last_error_type) && (
        <ErrorBanner
          errorType={listener.last_error_type ?? null}
          errorMessage={listener.last_error_message ?? null}
          traceback={listener.last_error_traceback ?? null}
          data-testid="handler-error-banner"
        />
      )}

      {/* Stats row */}
      <DetailStatsRow cells={handlerStatsCells(listener, lastInvokedLabel)} testId="handler-stats-row" />

      {/* View in code link */}
      {onSwitchToCode && listener.source_location && (
        <Button
          ghost
          size="sm"
          data-testid="view-in-code-btn"
          onClick={() => onSwitchToCode(sourceLine ?? undefined)}
        >
          view in code →
        </Button>
      )}
    </div>

    {/* Invocations panel */}
    <div class={styles.detailPaneInvocationsPanel}>
      <h3 class={styles.detailPanePanelHeading}>invocations</h3>
      {loading.value && !invocations.value ? (
        <Spinner />
      ) : (
        <ExecutionTable
          records={invocations.value ?? []}
          kind="handler"
          tableId={`invocation-table-${listener.listener_id}`}
        />
      )}
    </div>
    </div>
  );
}

interface JobDetailProps {
  job: JobData;
  onSwitchToCode?: (line?: number) => void;
}

function JobDetail({ job, onSwitchToCode }: JobDetailProps) {
  const { data: executions, loading, refetch } = useScopedApi(
    (since) => getJobExecutions(job.job_id, 50, since),
    { deps: [job.job_id] },
  );

  const { executionCompleted } = useAppState();
  const lastExecutedLabel = useRelativeTime(job.last_executed_at);
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const fireAtLabel = useRelativeTime(job.fire_at ?? null);

  // Targeted real-time refetch when a matching execution_completed event arrives
  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events?.some((e) => e.job_id === job.job_id) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);

  // Next-run strip
  const nextRunText = job.next_run
    ? `next ${nextRunLabel}`
    : job.fire_at
    ? `fire at ${fireAtLabel}`
    : null;

  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(job.source_location);

  const jobKind = jobStatusKind(job);

  return (
    <div class={styles.detailPaneWrapper} data-testid={`job-detail-${job.job_id}`}>
    <div class={styles.detailPaneContent}>
      {/* Header: kind badge + name + status pill */}
      <div class={styles.detailPaneHeader}>
        <Chip variant="kind" kind={jobKind} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={jobKind} size={8} />
          {kindLabel}
        </Chip>
        <span class={styles.detailPaneHandlerName}>
          {job.job_name}
          {job.name_auto && (
            <span
              class={styles.detailPaneNameAutoHint}
              title={`Auto-generated name. Pass name="..." when scheduling for something descriptive.`}
              aria-label="Auto-generated name"
            >ⓘ</span>
          )}
        </span>
      </div>

      {/* Subtitle: combined trigger label + detail */}
      {(job.trigger_label || job.trigger_detail) && (
        <p class={styles.detailPaneSubtitle}>
          {[job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null].filter(Boolean).join(" ")}
        </p>
      )}

      {/* Registration source */}
      {job.registration_source && (
        <div class={styles.detailPaneRegistration} data-testid="job-registration-source">
          <span class="ht-detail-label">Registration</span>
          <pre class={styles.detailPaneCodeSnippet}><code>{job.registration_source}</code></pre>
        </div>
      )}

      {/* Schedule chips */}
      <ScheduleChips job={job} />

      {/* Next-run strip */}
      {nextRunText && (
        <div class={styles.detailPaneNextRun} data-testid="job-next-run">
          <code class="ht-text-mono ht-text-sm ht-text-muted">{nextRunText}</code>
        </div>
      )}

      {/* Source file location */}
      {job.source_location && (
        <div class={styles.detailPaneSourceLoc} data-testid="job-source-location">
          <span class="ht-text-mono ht-text-sm ht-text-muted">
            {sourceFilename}{sourceLine ? `:${sourceLine}` : ""}
          </span>
        </div>
      )}

      {/* Error banner */}
      {jobKind === "err" && (job.last_error_message || job.last_error_type) && (
        <ErrorBanner
          errorType={job.last_error_type ?? null}
          errorMessage={job.last_error_message ?? null}
          traceback={job.last_error_traceback ?? null}
          data-testid="job-error-banner"
        />
      )}

      {/* Stats row */}
      <DetailStatsRow cells={jobStatsCells(job, lastExecutedLabel)} testId="job-stats-row" />

      {/* View in code link */}
      {onSwitchToCode && job.source_location && (
        <Button
          ghost
          size="sm"
          data-testid="view-in-code-btn"
          onClick={() => onSwitchToCode(sourceLine ?? undefined)}
        >
          view in code →
        </Button>
      )}
    </div>

    {/* Executions panel */}
    <div class={styles.detailPaneInvocationsPanel}>
      <h3 class={styles.detailPanePanelHeading}>executions</h3>
      {loading.value && !executions.value ? (
        <Spinner />
      ) : (
        <ExecutionTable
          records={executions.value ?? []}
          kind="job"
          tableId={`execution-table-${job.job_id}`}
        />
      )}
    </div>
    </div>
  );
}

/**
 * Parse a handler ID param (e.g. "h-42", "j-7") into kind and numeric id.
 * Returns null if the format is not recognized.
 */
function parseHandlerParam(param: string): { kind: "listener" | "job"; id: number } | null {
  const match = /^([hj])-(\d+)$/.exec(param);
  if (!match) return null;
  const id = parseInt(match[2], 10);
  if (match[1] === "h") return { kind: "listener", id };
  if (match[1] === "j") return { kind: "job", id };
  return null;
}

export function HandlersTab({ listeners, jobs, selectedHandler, appKey, instanceQs, onSwitchToCode }: Props) {
  const [, navigate] = useLocation();
  const correctUrl = useCorrectUrl();

  const isMobile = useSignal(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // ResizeObserver-based mobile detection (not media queries)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isMobile.value = entry.contentRect.width < BREAKPOINT_MOBILE;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isMobile]);

  const hasItems = listeners.length > 0 || jobs.length > 0;

  // Parse selectedHandler param into kind + id
  const parsed = selectedHandler ? parseHandlerParam(selectedHandler) : null;

  // Resolve selected listener/job from URL-driven selection
  const selectedListener = parsed?.kind === "listener"
    ? listeners.find((l) => l.listener_id === parsed.id) ?? null
    : null;
  const selectedJob = parsed?.kind === "job"
    ? jobs.find((j) => j.job_id === parsed.id) ?? null
    : null;

  // correctUrl guard: only fire when data is loaded (at least one listener or job exists)
  // and the handler ID from the URL doesn't match any item.
  useEffect(() => {
    if (!selectedHandler || !parsed) return;
    if (!hasItems) return; // still loading — don't correct yet
    const found = parsed.kind === "listener"
      ? listeners.some((l) => l.listener_id === parsed.id)
      : jobs.some((j) => j.job_id === parsed.id);
    if (!found) {
      correctUrl(`/apps/${appKey}/handlers${instanceQs}`);
    }
  }, [selectedHandler, parsed, hasItems, listeners, jobs, appKey, instanceQs, correctUrl]);

  const handleSelect = (id: SelectedHandlerId) => {
    const kindPrefix = id.kind === "listener" ? "h" : "j";
    navigate(`/apps/${appKey}/handlers/${kindPrefix}-${id.id}${instanceQs}`);
  };

  if (!hasItems) {
    return (
      <div data-testid="handlers-empty">
        <EmptyState title="no handlers or scheduled jobs registered." />
      </div>
    );
  }

  // On mobile: show detail pane when a handler is selected (selectedHandler !== null)
  const showMobileDetail = isMobile.value && selectedHandler !== null;
  const showMasterList = !isMobile.value || selectedHandler === null;
  const showDetailPane = !isMobile.value || selectedHandler !== null;

  // Current selection for HandlerList highlight
  const selectedId: SelectedHandlerId | null = parsed
    ? { kind: parsed.kind, id: parsed.id }
    : null;

  return (
    <div ref={containerRef}>
      {/* Health strip — above master/detail layout */}
      <HandlersHealthStrip listeners={listeners} jobs={jobs} />

      {/* Mobile: back button in detail view — navigate to handler list (no handler ID) */}
      {showMobileDetail && (
        <Button
          ghost
          size="sm"
          class="ht-mb-3"
          data-testid="back-to-list"
          onClick={() => navigate(`/apps/${appKey}/handlers${instanceQs}`)}
          aria-label="Back to handler list"
        >
          ← back
        </Button>
      )}

      <div class={clsx(styles.masterDetail, isMobile.value && styles.masterDetailMobile)}>
        {/* Master list */}
        {showMasterList && (
          <div class={styles.masterDetailList}>
            <HandlerList
              listeners={listeners}
              jobs={jobs}
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </div>
        )}

        {/* Detail pane */}
        {showDetailPane && (
          <div class={styles.masterDetailDetail}>
            {selectedListener ? (
              <ListenerDetail listener={selectedListener} onSwitchToCode={onSwitchToCode} />
            ) : selectedJob ? (
              <JobDetail job={selectedJob} onSwitchToCode={onSwitchToCode} />
            ) : (
              <EmptyState icon="←" title="Select a handler or job to see details." data-testid="detail-placeholder" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
