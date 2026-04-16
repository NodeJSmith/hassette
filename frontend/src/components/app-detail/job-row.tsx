import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getJobExecutions } from "../../api/endpoints";
import type { JobData } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { formatDuration, pluralize } from "../../utils/format";
import { JobExecutions } from "./job-executions";

interface Props {
  job: JobData;
  onGroupClick?: (group: string) => void;
}

/**
 * Expandable job row with lazy-loaded execution history.
 *
 * Uses `useScopedApi` with `lazy: true` so no API call is made until the row is
 * expanded. On re-expand, `refetch()` is called again — stale data stays
 * visible during the refresh (stale-while-revalidate).
 */
export function JobRow({ job, onGroupClick }: Props) {
  const lastExecuted = useRelativeTime(job.last_executed_at);
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const expanded = useRef(signal(false)).current;

  const { data: executions, loading, refetch } = useScopedApi(
    (sid) => getJobExecutions(job.job_id, 50, sid),
    { deps: [job.job_id], lazy: true },
  );

  const dotClass =
    job.failed > 0 ? "danger" : job.total_executions > 0 ? "success" : "neutral";

  const hasExecutions = job.total_executions > 0;
  const toggle = () => {
    if (!hasExecutions) return;
    expanded.value = !expanded.value;
    if (expanded.value) {
      void refetch();
    }
  };

  // Subtitle primary: trigger_label when non-empty, otherwise trigger_type
  const subtitlePrimary = job.trigger_label !== "" ? job.trigger_label : (job.trigger_type ?? "");

  return (
    <div
      class={`ht-item-row${job.cancelled ? " is-cancelled" : ""}`}
      data-testid={`job-row-${job.job_id}`}
    >
      <div
        class="ht-item-row__main"
        role={hasExecutions ? "button" : undefined}
        tabIndex={hasExecutions ? 0 : undefined}
        aria-expanded={hasExecutions ? expanded.value : undefined}
        onClick={toggle}
        onKeyDown={hasExecutions ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } } : undefined}
      >
        <span class={`ht-item-row__dot ht-item-row__dot--${dotClass}`} />
        <div class="ht-item-row__content">
          <span class="ht-item-row__title">{job.job_name}</span>
          {subtitlePrimary && (
            <span class="ht-item-row__subtitle">
              {subtitlePrimary}
              {job.trigger_detail !== null && job.trigger_detail !== undefined && (
                <span class="ht-text-muted"> · {job.trigger_detail}</span>
              )}
            </span>
          )}
          {(job.group !== null && job.group !== undefined || job.jitter !== null && job.jitter !== undefined || job.cancelled) && (
            <span class="ht-item-row__subtitle">
              {job.group !== null && job.group !== undefined && (
                onGroupClick ? (
                  <button
                    type="button"
                    class="ht-badge ht-badge--group"
                    onClick={(e) => {
                      e.stopPropagation();
                      onGroupClick(job.group!);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        onGroupClick(job.group!);
                      }
                    }}
                  >
                    {job.group}
                  </button>
                ) : (
                  <span class="ht-badge ht-badge--group">{job.group}</span>
                )
              )}
              {job.jitter !== null && job.jitter !== undefined && (
                <span class="ht-tag ht-tag--jitter">±{job.jitter}s</span>
              )}
              {job.cancelled && (
                <span class="ht-badge ht-badge--cancelled" data-testid="cancelled-badge">Cancelled</span>
              )}
            </span>
          )}
        </div>
        <div class="ht-item-row__stats">
          <span class="ht-meta-item" title="Total executions">
            {pluralize(job.total_executions, "run")}
          </span>
          {job.failed > 0 && (
            <span class="ht-meta-item--strong ht-text-danger">{job.failed} failed</span>
          )}
          {job.avg_duration_ms > 0 && (
            <span class="ht-meta-item">{formatDuration(job.avg_duration_ms)} avg</span>
          )}
          {lastExecuted && (
            <span class="ht-meta-item ht-text-muted">
              {lastExecuted}
            </span>
          )}
        </div>
        {job.total_executions > 0 && (
          <span class={`ht-item-row__chevron${expanded.value ? " is-open" : ""}`}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" />
            </svg>
          </span>
        )}
      </div>
      {expanded.value && (
        <div class="ht-item-detail" id={`job-${job.job_id}-detail`}>
          {job.next_run !== null && job.next_run !== undefined && (
            <p class="ht-next-run ht-text-xs">
              Next: {nextRunLabel}
              {job.jitter !== null && job.jitter !== undefined && <span class="ht-text-muted"> (±{job.jitter}s jitter)</span>}
            </p>
          )}
          {(job.source_location || job.registration_source) && (
            <div class="ht-source-display" data-testid="source-display">
              {job.source_location && (
                <div class="ht-text-muted ht-text-xs">{job.source_location}</div>
              )}
              {job.registration_source && (
                <code class="ht-text-mono ht-text-xs" style="display: block">{job.registration_source}</code>
              )}
            </div>
          )}
          {loading.value && !executions.value ? (
            <p class="ht-text-muted ht-text-xs">Loading executions...</p>
          ) : executions.value ? (
            <JobExecutions executions={executions.value} jobId={job.job_id} />
          ) : null}
        </div>
      )}
    </div>
  );
}
