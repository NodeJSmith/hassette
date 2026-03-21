import { formatDuration, formatTimestamp } from "../../utils/format";

interface Execution {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
}

interface Props {
  executions: Execution[];
  jobId: number;
}

export function JobExecutions({ executions, jobId }: Props) {
  if (executions.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No executions recorded.</p>;
  }

  return (
    <table class="ht-table ht-table--compact" data-testid={`execution-table-${jobId}`}>
      <thead>
        <tr>
          <th>Status</th>
          <th>Timestamp</th>
          <th>Duration</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {executions.map((ex, i) => (
          <tr key={i}>
            <td><span class={`ht-badge ht-badge--sm ht-badge--${ex.status === "success" ? "success" : "danger"}`}>{ex.status}</span></td>
            <td class="ht-text-mono ht-text-xs">{formatTimestamp(ex.execution_start_ts)}</td>
            <td>{formatDuration(ex.duration_ms)}</td>
            <td class="ht-text-secondary ht-text-sm">{ex.error_message ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
