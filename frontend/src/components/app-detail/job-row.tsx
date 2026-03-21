import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getJobExecutions } from "../../api/endpoints";
import { formatDuration, formatRelativeTime } from "../../utils/format";
import { JobExecutions } from "./job-executions";

interface JobData {
  job_id: number;
  job_name: string;
  handler_method: string;
  trigger_type: string | null;
  total_executions: number;
  failed: number;
  avg_duration_ms: number;
  last_executed_at: number | null;
}

interface Props {
  job: JobData;
}

export function JobRow({ job }: Props) {
  const expanded = useRef(signal(false)).current;
  const loaded = useRef(signal(false)).current;
  const executions = useRef(signal<unknown[]>([])).current;
  const loading = useRef(signal(false)).current;

  const dotClass =
    job.failed > 0 ? "danger" : job.total_executions > 0 ? "success" : "neutral";

  const toggle = async () => {
    expanded.value = !expanded.value;
    if (expanded.value && !loaded.value) {
      loading.value = true;
      try {
        executions.value = await getJobExecutions(job.job_id);
        loaded.value = true;
      } finally {
        loading.value = false;
      }
    }
  };

  return (
    <div class="ht-item-row" data-testid={`job-row-${job.job_id}`}>
      <div
        class="ht-item-row__main"
        role="button"
        tabindex={0}
        aria-expanded={expanded.value}
        onClick={() => void toggle()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void toggle(); } }}
      >
        <span class={`ht-item-row__dot ht-item-row__dot--${dotClass}`} />
        <div class="ht-item-row__content">
          <span class="ht-item-row__title">{job.job_name}</span>
          {job.trigger_type && (
            <span class="ht-item-row__subtitle">{job.trigger_type}</span>
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
        <span class={`ht-item-row__chevron${expanded.value ? " is-open" : ""}`} />
      </div>
      {expanded.value && (
        <div class="ht-item-row__detail" id={`job-${job.job_id}-detail`}>
          {loading.value ? (
            <p class="ht-text-muted ht-text-xs">Loading executions...</p>
          ) : (
            <JobExecutions executions={executions.value as never[]} />
          )}
        </div>
      )}
    </div>
  );
}
