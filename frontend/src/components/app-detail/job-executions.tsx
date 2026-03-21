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
}

export function JobExecutions({ executions }: Props) {
  if (executions.length === 0) {
    return <p class="ht-text-secondary ht-text-sm">No executions recorded.</p>;
  }

  return (
    <table class="ht-table ht-table-compact">
      <thead>
        <tr>
          <th>Time</th>
          <th>Duration</th>
          <th>Status</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {executions.map((ex, i) => (
          <tr key={i}>
            <td>{formatTimestamp(ex.execution_start_ts)}</td>
            <td>{formatDuration(ex.duration_ms)}</td>
            <td><span class={`ht-tag ht-tag-${ex.status}`}>{ex.status}</span></td>
            <td class="ht-text-secondary ht-text-sm">{ex.error_message ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
