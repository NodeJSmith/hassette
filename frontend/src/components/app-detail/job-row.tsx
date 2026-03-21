import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getJobExecutions } from "../../api/endpoints";
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
    <>
      <tr
        class={`ht-item-row ht-item-row-expandable${expanded.value ? " expanded" : ""}`}
        onClick={() => void toggle()}
        data-testid={`job-row-${job.job_id}`}
      >
        <td class="ht-item-row-toggle">{expanded.value ? "▾" : "▸"}</td>
        <td>
          <code class="ht-text-sm">{job.job_name}</code>
          {job.trigger_type && (
            <div class="ht-text-secondary ht-text-xs">{job.trigger_type}</div>
          )}
        </td>
        <td class="ht-text-mono">{job.total_executions}</td>
        <td class="ht-text-mono">{job.failed}</td>
        <td>{job.avg_duration_ms > 0 ? `${job.avg_duration_ms.toFixed(0)}ms` : "—"}</td>
      </tr>
      {expanded.value && (
        <tr class="ht-item-row-detail">
          <td colSpan={5}>
            {loading.value ? (
              <p class="ht-text-secondary">Loading executions...</p>
            ) : (
              <JobExecutions executions={executions.value as never[]} />
            )}
          </td>
        </tr>
      )}
    </>
  );
}
