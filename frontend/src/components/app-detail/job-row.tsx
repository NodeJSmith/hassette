import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getJobExecutions } from "../../api/endpoints";
import type { JobData } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { formatDuration, formatRelativeTime } from "../../utils/format";
import { JobExecutions } from "./job-executions";

interface Props {
  job: JobData;
}

/**
 * Expandable job row with lazy-loaded execution history.
 *
 * Uses `useApi` with `lazy: true` so no API call is made until the row is
 * expanded. On re-expand, `refetch()` is called again — stale data stays
 * visible during the refresh (stale-while-revalidate).
 */
export function JobRow({ job }: Props) {
  const expanded = useRef(signal(false)).current;

  const { data: executions, loading, refetch } = useApi(
    () => getJobExecutions(job.job_id),
    [job.job_id],
    { lazy: true },
  );

  const dotClass =
    job.failed > 0 ? "danger" : job.total_executions > 0 ? "success" : "neutral";

  const toggle = () => {
    expanded.value = !expanded.value;
    if (expanded.value) {
      void refetch();
    }
  };

  return (
    <div class="ht-item-row" data-testid={`job-row-${job.job_id}`}>
      <div
        class="ht-item-row__main"
        role="button"
        tabIndex={0}
        aria-expanded={expanded.value}
        onClick={toggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
      >
        <span class={`ht-item-row__dot ht-item-row__dot--${dotClass}`} />
        <div class="ht-item-row__content">
          <span class="ht-item-row__title">{job.job_name}</span>
          {(job.trigger_type || job.handler_method) && (
            <span class="ht-item-row__subtitle">
              {job.trigger_type
                ? `${job.trigger_type}${job.trigger_value ? `: ${job.trigger_value}` : ""}`
                : job.handler_method}
            </span>
          )}
        </div>
        <div class="ht-item-row__stats">
          <span class="ht-meta-item" title="Total executions">
            {job.total_executions} runs
          </span>
          {job.failed > 0 && (
            <span class="ht-meta-item--strong ht-text-danger">{job.failed} failed</span>
          )}
          {job.avg_duration_ms > 0 && (
            <span class="ht-meta-item">{formatDuration(job.avg_duration_ms)} avg</span>
          )}
          {job.last_executed_at && (
            <span class="ht-meta-item ht-text-muted">
              {formatRelativeTime(job.last_executed_at)}
            </span>
          )}
        </div>
        <span class={`ht-item-row__chevron${expanded.value ? " is-open" : ""}`}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 2 8 6 4 10" />
          </svg>
        </span>
      </div>
      {expanded.value && (
        <div class="ht-item-detail" id={`job-${job.job_id}-detail`}>
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
