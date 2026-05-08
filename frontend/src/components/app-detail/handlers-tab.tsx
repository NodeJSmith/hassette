import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import type { ListenerData, JobData } from "../../api/endpoints";
import { getHandlerInvocations, getJobExecutions } from "../../api/endpoints";
import { HandlerList, type SelectedHandlerId } from "./handler-list";
import { HandlerInvocations } from "./handler-invocations";
import { JobExecutions } from "./job-executions";
import { HandlersHealthStrip } from "./health-strip";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useDebouncedEffect } from "../../hooks/use-debounced-effect";
import { formatTriggerDetail, formatDuration, formatRelativeTime, lastDotSegment, parseSourceLocation, TIME_PRESET_LABELS } from "../../utils/format";
import { handlerKindLabel, statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";

const MOBILE_BREAKPOINT = 768;

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  focusMethod: string | null;
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
    <div class="ht-chip-row" data-testid="modifier-chips">
      {chips.map((c) => (
        <span key={c.label} class="ht-chip ht-chip--modifier">
          {c.label}{c.value ? ` ${c.value}` : ""}
        </span>
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
    <div class="ht-chip-row" data-testid="schedule-chips">
      {chips.map((c) => (
        <span key={c.label} class="ht-chip ht-chip--schedule">{c.label}</span>
      ))}
    </div>
  );
}

/** Stats row: CALLS · 1H, SUCCESSFUL, LAST, FAILED, TIMED OUT, CANCELLED (conditional), MIN / AVG / MAX */
function HandlerStatsRow({ listener }: { listener: ListenerData }) {
  const { timePreset } = useAppState();
  const timeLabel = TIME_PRESET_LABELS[timePreset.value] ?? "";
  const lastLabel = listener.last_invoked_at
    ? formatRelativeTime(listener.last_invoked_at)
    : "—";
  const minLabel = listener.min_duration_ms !== null && listener.min_duration_ms !== undefined ? formatDuration(listener.min_duration_ms) : "—";
  const maxLabel = listener.max_duration_ms !== null && listener.max_duration_ms !== undefined ? formatDuration(listener.max_duration_ms) : "—";

  return (
    <div class="ht-detail-stats-row" data-testid="handler-stats-row">
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Calls{timeLabel ? ` · ${timeLabel}` : ""}</span>
        <span class="ht-detail-stats-row__value">{listener.total_invocations}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Successful</span>
        <span class="ht-detail-stats-row__value">{listener.successful}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Last</span>
        <span class="ht-detail-stats-row__value">{lastLabel}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Failed</span>
        <span class={`ht-detail-stats-row__value${listener.failed > 0 ? " ht-detail-stats-row__value--err" : ""}`}>
          {listener.failed > 0 ? listener.failed : "—"}
        </span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Timed Out</span>
        <span class={`ht-detail-stats-row__value${listener.timed_out > 0 ? " ht-detail-stats-row__value--warn" : ""}`}>
          {listener.timed_out > 0 ? listener.timed_out : "—"}
        </span>
      </div>
      {listener.cancelled > 0 && (
        <div class="ht-detail-stats-row__cell">
          <span class="ht-detail-stats-row__label">Cancelled</span>
          <span class="ht-detail-stats-row__value">{listener.cancelled}</span>
        </div>
      )}
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Min</span>
        <span class="ht-detail-stats-row__value">{minLabel}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Avg</span>
        <span class="ht-detail-stats-row__value">
          {listener.avg_duration_ms > 0 ? formatDuration(listener.avg_duration_ms) : "—"}
        </span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Max</span>
        <span class="ht-detail-stats-row__value">{maxLabel}</span>
      </div>
    </div>
  );
}

/** Stats row for scheduled jobs: RUNS · 1H, SUCCESSFUL, LAST, FAILED, TIMED OUT, MIN / AVG / MAX */
function JobStatsRow({ job }: { job: JobData }) {
  const { timePreset } = useAppState();
  const timeLabel = TIME_PRESET_LABELS[timePreset.value] ?? "";
  const lastLabel = job.last_executed_at
    ? formatRelativeTime(job.last_executed_at)
    : "—";
  const minLabel = job.min_duration_ms !== null && job.min_duration_ms !== undefined ? formatDuration(job.min_duration_ms) : "—";
  const maxLabel = job.max_duration_ms !== null && job.max_duration_ms !== undefined ? formatDuration(job.max_duration_ms) : "—";

  return (
    <div class="ht-detail-stats-row" data-testid="job-stats-row">
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Runs{timeLabel ? ` · ${timeLabel}` : ""}</span>
        <span class="ht-detail-stats-row__value">{job.total_executions}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Successful</span>
        <span class="ht-detail-stats-row__value">{job.successful}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Last</span>
        <span class="ht-detail-stats-row__value">{lastLabel}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Failed</span>
        <span class={`ht-detail-stats-row__value${job.failed > 0 ? " ht-detail-stats-row__value--err" : ""}`}>
          {job.failed > 0 ? job.failed : "—"}
        </span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Timed Out</span>
        <span class={`ht-detail-stats-row__value${job.timed_out > 0 ? " ht-detail-stats-row__value--warn" : ""}`}>
          {job.timed_out > 0 ? job.timed_out : "—"}
        </span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Min</span>
        <span class="ht-detail-stats-row__value">{minLabel}</span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Avg</span>
        <span class="ht-detail-stats-row__value">
          {job.avg_duration_ms > 0 ? formatDuration(job.avg_duration_ms) : "—"}
        </span>
      </div>
      <div class="ht-detail-stats-row__cell">
        <span class="ht-detail-stats-row__label">Max</span>
        <span class="ht-detail-stats-row__value">{maxLabel}</span>
      </div>
    </div>
  );
}


interface ErrorBannerProps {
  errorType: string | null;
  errorMessage: string | null;
  traceback: string | null;
  testId?: string;
}

function ErrorBanner({ errorType, errorMessage, traceback, testId }: ErrorBannerProps) {
  const [traceExpanded, setTraceExpanded] = useState(false);

  return (
    <div class="ht-detail-pane__error-banner" data-testid={testId}>
      <span class="ht-detail-pane__error-banner-heading">
        Last Error{errorType ? ` — ${errorType}` : ""}
      </span>
      {errorMessage && (
        <p class="ht-detail-pane__error-banner-message">{errorMessage}</p>
      )}
      {traceback && (
        <div class="ht-detail-pane__traceback" data-testid="traceback-content">
          <button
            type="button"
            class="ht-detail-pane__traceback-toggle"
            data-testid="traceback-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((v) => !v)}
          >
            {traceExpanded ? "hide traceback" : "show traceback"}
          </button>
          {traceExpanded && (
            <pre class="ht-traceback ht-detail-pane__traceback-body">{traceback}</pre>
          )}
        </div>
      )}
    </div>
  );
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

  // Targeted real-time refetch when a matching invocation_completed event arrives
  useDebouncedEffect(
    () => invocationCompleted.value,
    500,
    () => {
      const events = invocationCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.listener_id === listener.listener_id);
      if (matches) void refetch();
    },
  );

  const kindLabel = handlerKindLabel("listener", listener.listener_kind, null);
  const isFailing = listener.failed > 0 || listener.timed_out > 0;
  const listenerKind = isFailing ? statusToKind("failed") : statusToKind("running");
  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(listener.source_location);

  return (
    <div class="ht-detail-pane__wrapper" data-testid={`listener-detail-${listener.listener_id}`}>
    <div class="ht-detail-pane__content">
      {/* Header: kind badge + name + status pill */}
      <div class="ht-detail-pane__header">
        <span class={`ht-kind-badge ht-kind-badge--${listenerKind}`} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={listenerKind} size={8} />
          {kindLabel}
        </span>
        <span class="ht-detail-pane__handler-name">{lastDotSegment(listener.handler_method)}</span>
        {isFailing && (
          <span class="ht-badge ht-badge--danger ht-badge--sm" data-testid="handler-status-pill">failing</span>
        )}
      </div>

      {/* Subtitle: human_description */}
      {listener.human_description && (
        <p class="ht-detail-pane__subtitle" data-testid="handler-human-description">
          {listener.human_description}
        </p>
      )}

      {/* Registration source: actual code snippet */}
      {listener.registration_source && (
        <div class="ht-detail-pane__registration" data-testid="handler-registration-source">
          <span class="ht-detail-label">Registration</span>
          <pre class="ht-detail-pane__code-snippet"><code>{listener.registration_source}</code></pre>
        </div>
      )}

      {/* Modifier chips */}
      <ModifierChips listener={listener} />

      {/* Source file location */}
      {listener.source_location && (
        <div class="ht-detail-pane__source-loc" data-testid="handler-source-location">
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
          testId="handler-error-banner"
        />
      )}

      {/* Stats row */}
      <HandlerStatsRow listener={listener} />

      {/* View in code link */}
      {onSwitchToCode && listener.source_location && (
        <button
          type="button"
          class="ht-btn ht-btn--ghost ht-btn--sm"
          data-testid="view-in-code-btn"
          onClick={() => onSwitchToCode(sourceLine ?? undefined)}
        >
          view in code →
        </button>
      )}
    </div>

    {/* Invocations panel */}
    <div class="ht-detail-pane__invocations-panel">
      <h3 class="ht-detail-pane__panel-heading">invocations</h3>
      {loading.value && !invocations.value ? (
        <p class="ht-text-muted ht-text-xs">Loading invocations…</p>
      ) : (
        <HandlerInvocations
          invocations={invocations.value ?? []}
          listenerId={listener.listener_id}
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

  // Targeted real-time refetch when a matching execution_completed event arrives
  useDebouncedEffect(
    () => executionCompleted.value,
    500,
    () => {
      const events = executionCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.job_id === job.job_id);
      if (matches) void refetch();
    },
  );

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);

  // Next-run strip
  const nextRunText = job.cancelled
    ? "cancelled"
    : job.next_run
    ? `next ${formatRelativeTime(job.next_run)}`
    : job.fire_at
    ? `fire at ${formatRelativeTime(job.fire_at)}`
    : null;

  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(job.source_location);

  const jobKind = job.cancelled ? statusToKind("disabled") : (job.failed > 0 ? statusToKind("failed") : statusToKind("running"));

  return (
    <div class="ht-detail-pane__wrapper" data-testid={`job-detail-${job.job_id}`}>
    <div class="ht-detail-pane__content">
      {/* Header: kind badge + name + status pill */}
      <div class="ht-detail-pane__header">
        <span class={`ht-kind-badge ht-kind-badge--${jobKind}`} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={jobKind} size={8} />
          {kindLabel}
        </span>
        <span class="ht-detail-pane__handler-name">
          {job.job_name}
          {job.name_auto && (
            <span
              class="ht-detail-pane__name-auto-hint"
              title={`Auto-generated name. Pass name="..." when scheduling for something descriptive.`}
              aria-label="Auto-generated name"
            >ⓘ</span>
          )}
        </span>
        {job.cancelled && (
          <span class="ht-badge ht-badge--neutral ht-badge--sm" data-testid="job-status-pill">cancelled</span>
        )}
      </div>

      {/* Subtitle: combined trigger label + detail */}
      {(job.trigger_label || job.trigger_detail) && (
        <p class="ht-detail-pane__subtitle">
          {[job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null].filter(Boolean).join(" ")}
        </p>
      )}

      {/* Registration source */}
      {job.registration_source && (
        <div class="ht-detail-pane__registration" data-testid="job-registration-source">
          <span class="ht-detail-label">Registration</span>
          <pre class="ht-detail-pane__code-snippet"><code>{job.registration_source}</code></pre>
        </div>
      )}

      {/* Schedule chips */}
      <ScheduleChips job={job} />

      {/* Next-run strip */}
      {nextRunText && (
        <div class="ht-detail-pane__next-run" data-testid="job-next-run">
          <code class="ht-text-mono ht-text-sm ht-text-muted">{nextRunText}</code>
        </div>
      )}

      {/* Source file location */}
      {job.source_location && (
        <div class="ht-detail-pane__source-loc" data-testid="job-source-location">
          <span class="ht-text-mono ht-text-sm ht-text-muted">
            {sourceFilename}{sourceLine ? `:${sourceLine}` : ""}
          </span>
        </div>
      )}

      {/* Error banner */}
      {(job.failed > 0 || job.timed_out > 0) && (job.last_error_message || job.last_error_type) && (
        <ErrorBanner
          errorType={job.last_error_type ?? null}
          errorMessage={job.last_error_message ?? null}
          traceback={job.last_error_traceback ?? null}
          testId="job-error-banner"
        />
      )}

      {/* Stats row */}
      <JobStatsRow job={job} />

      {/* View in code link */}
      {onSwitchToCode && job.source_location && (
        <button
          type="button"
          class="ht-btn ht-btn--ghost ht-btn--sm"
          data-testid="view-in-code-btn"
          onClick={() => onSwitchToCode(sourceLine ?? undefined)}
        >
          view in code →
        </button>
      )}
    </div>

    {/* Executions panel */}
    <div class="ht-detail-pane__invocations-panel">
      <h3 class="ht-detail-pane__panel-heading">executions</h3>
      {loading.value && !executions.value ? (
        <p class="ht-text-muted ht-text-xs">Loading executions…</p>
      ) : (
        <JobExecutions
          executions={executions.value ?? []}
          jobId={job.job_id}
        />
      )}
    </div>
    </div>
  );
}

export function HandlersTab({ listeners, jobs, focusMethod, onSwitchToCode }: Props) {
  const { timePreset } = useAppState();
  // useRef(signal(...)).current — stable signal that survives re-renders without triggering them
  const selectedId = useRef(signal<SelectedHandlerId | null>(null)).current;
  // Mobile mode: show detail instead of list
  const showDetail = useRef(signal(false)).current;
  // Whether we're in mobile layout (< MOBILE_BREAKPOINT px)
  const isMobile = useRef(signal(false)).current;

  const containerRef = useRef<HTMLDivElement>(null);

  // ResizeObserver-based mobile detection (not media queries)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isMobile.value = entry.contentRect.width < MOBILE_BREAKPOINT;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isMobile]);

  // Auto-select based on focusMethod
  useEffect(() => {
    if (!focusMethod) return;
    const match = listeners.find((l) => l.handler_method === focusMethod);
    if (match) {
      selectedId.value = { kind: "listener", id: match.listener_id };
      if (isMobile.value) showDetail.value = true;
    }
  }, [focusMethod, listeners, selectedId, isMobile, showDetail]);

  const handleSelect = (id: SelectedHandlerId) => {
    selectedId.value = id;
    if (isMobile.value) showDetail.value = true;
  };

  const handleBack = () => {
    showDetail.value = false;
  };

  const hasItems = listeners.length > 0 || jobs.length > 0;

  if (!hasItems) {
    return (
      <div class="ht-handlers-tab" data-testid="handlers-empty">
        <p class="ht-text-muted">no handlers or scheduled jobs registered.</p>
      </div>
    );
  }

  // Resolve selected item
  const selectedListener = selectedId.value?.kind === "listener"
    ? listeners.find((l) => l.listener_id === selectedId.value!.id) ?? null
    : null;
  const selectedJob = selectedId.value?.kind === "job"
    ? jobs.find((j) => j.job_id === selectedId.value!.id) ?? null
    : null;

  const showMobileDetail = isMobile.value && showDetail.value;
  const showMasterList = !isMobile.value || !showDetail.value;
  const showDetailPane = !isMobile.value || showDetail.value;

  return (
    <div class="ht-handlers-tab" ref={containerRef}>
      {/* Health strip — above master/detail layout */}
      <HandlersHealthStrip listeners={listeners} jobs={jobs} timeLabel={TIME_PRESET_LABELS[timePreset.value] ?? ""} />

      {/* Mobile: back button in detail view */}
      {showMobileDetail && (
        <button
          type="button"
          class="ht-btn ht-btn--ghost ht-btn--sm ht-mb-3"
          data-testid="back-to-list"
          onClick={handleBack}
          aria-label="Back to handler list"
        >
          ← back
        </button>
      )}

      <div class={`ht-master-detail${isMobile.value ? " ht-master-detail--mobile" : ""}`}>
        {/* Master list */}
        {showMasterList && (
          <div class="ht-master-detail__list">
            <HandlerList
              listeners={listeners}
              jobs={jobs}
              selectedId={selectedId.value}
              onSelect={handleSelect}
            />
          </div>
        )}

        {/* Detail pane */}
        {showDetailPane && (
          <div class="ht-master-detail__detail">
            {selectedListener ? (
              <ListenerDetail listener={selectedListener} onSwitchToCode={onSwitchToCode} />
            ) : selectedJob ? (
              <JobDetail job={selectedJob} onSwitchToCode={onSwitchToCode} />
            ) : (
              <div class="ht-detail-pane__empty" data-testid="detail-placeholder">
                <p class="ht-text-muted">Select a handler or job to see details.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
