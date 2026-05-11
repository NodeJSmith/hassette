import { useEffect, useRef } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import { useLocation } from "wouter";
import type { ListenerData, JobData } from "../../api/endpoints";
import { getHandlerInvocations, getJobExecutions } from "../../api/endpoints";
import { HandlerList, type SelectedHandlerId, listenerStatusKind, jobStatusKind } from "./handler-list";
import { HandlerInvocations } from "./handler-invocations";
import { JobExecutions } from "./job-executions";
import { HandlersHealthStrip } from "./health-strip";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useCorrectUrl } from "../../hooks/use-correct-url";
import { useDebouncedEffect } from "../../hooks/use-debounced-effect";
import { formatTriggerDetail, formatDurationOrDash, formatOptionalDuration, formatRelativeTime, lastDotSegment, parseSourceLocation, TIME_PRESET_LABELS } from "../../utils/format";

import { handlerKindLabel } from "../../utils/status";
import { BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { EmptyState } from "../shared/empty-state";
import { ErrorBanner } from "../shared/error-banner";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";


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

interface StatsCell {
  label: string;
  value: string | number;
  tone?: "err" | "warn";
}

function DetailStatsRow({ cells, testId }: { cells: StatsCell[]; testId?: string }) {
  return (
    <div class="ht-detail-stats-row" data-testid={testId}>
      {cells.map((cell) => (
        <div class="ht-detail-stats-row__cell" key={cell.label}>
          <span class="ht-detail-stats-row__label">{cell.label}</span>
          <span class={`ht-detail-stats-row__value${cell.tone ? ` ht-detail-stats-row__value--${cell.tone}` : ""}`}>
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function handlerStatsCells(listener: ListenerData, timeLabel: string): StatsCell[] {
  const cells: StatsCell[] = [
    { label: `Calls${timeLabel ? ` · ${timeLabel}` : ""}`, value: listener.total_invocations },
    { label: "Successful", value: listener.successful },
    { label: "Last", value: listener.last_invoked_at ? formatRelativeTime(listener.last_invoked_at) : "—" },
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

function jobStatsCells(job: JobData, timeLabel: string): StatsCell[] {
  return [
    { label: `Runs${timeLabel ? ` · ${timeLabel}` : ""}`, value: job.total_executions },
    { label: "Successful", value: job.successful },
    { label: "Last", value: job.last_executed_at ? formatRelativeTime(job.last_executed_at) : "—" },
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

  const { invocationCompleted, effectiveTimePreset } = useAppState();
  const timeLabel = TIME_PRESET_LABELS[effectiveTimePreset.value] ?? "";

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
  const listenerKind = listenerStatusKind(listener);
  const isFailing = listenerKind === "err";
  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(listener.source_location);

  return (
    <div class="ht-detail-pane__wrapper" data-testid={`listener-detail-${listener.listener_id}`}>
    <div class="ht-detail-pane__content">
      {/* Header: kind badge + name + status pill */}
      <div class="ht-detail-pane__header">
        <span class={`ht-chip ht-chip--kind ht-chip--kind-${listenerKind}`} aria-label={`kind: ${kindLabel}`}>
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
          data-testid="handler-error-banner"
        />
      )}

      {/* Stats row */}
      <DetailStatsRow cells={handlerStatsCells(listener, timeLabel)} testId="handler-stats-row" />

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
        <Spinner />
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

  const { executionCompleted, effectiveTimePreset: jobEffectivePreset } = useAppState();
  const jobTimeLabel = TIME_PRESET_LABELS[jobEffectivePreset.value] ?? "";

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
  const nextRunText = job.next_run
    ? `next ${formatRelativeTime(job.next_run)}`
    : job.fire_at
    ? `fire at ${formatRelativeTime(job.fire_at)}`
    : null;

  const { filename: sourceFilename, line: sourceLine } = parseSourceLocation(job.source_location);

  const jobKind = jobStatusKind(job);

  return (
    <div class="ht-detail-pane__wrapper" data-testid={`job-detail-${job.job_id}`}>
    <div class="ht-detail-pane__content">
      {/* Header: kind badge + name + status pill */}
      <div class="ht-detail-pane__header">
        <span class={`ht-chip ht-chip--kind ht-chip--kind-${jobKind}`} aria-label={`kind: ${kindLabel}`}>
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
          data-testid="job-error-banner"
        />
      )}

      {/* Stats row */}
      <DetailStatsRow cells={jobStatsCells(job, jobTimeLabel)} testId="job-stats-row" />

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
        <Spinner />
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
  const { effectiveTimePreset } = useAppState();
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
      <div class="ht-handlers-tab" data-testid="handlers-empty">
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
    <div class="ht-handlers-tab" ref={containerRef}>
      {/* Health strip — above master/detail layout */}
      <HandlersHealthStrip listeners={listeners} jobs={jobs} timeLabel={TIME_PRESET_LABELS[effectiveTimePreset.value] ?? ""} />

      {/* Mobile: back button in detail view — navigate to handler list (no handler ID) */}
      {showMobileDetail && (
        <button
          type="button"
          class="ht-btn ht-btn--ghost ht-btn--sm ht-mb-3"
          data-testid="back-to-list"
          onClick={() => navigate(`/apps/${appKey}/handlers${instanceQs}`)}
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
              selectedId={selectedId}
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
              <EmptyState icon="←" title="Select a handler or job to see details." data-testid="detail-placeholder" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
