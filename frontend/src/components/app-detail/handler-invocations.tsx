import { formatDuration, formatTimestamp } from "../../utils/format";

interface Invocation {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
}

interface Props {
  invocations: Invocation[];
}

export function HandlerInvocations({ invocations }: Props) {
  if (invocations.length === 0) {
    return <p class="ht-text-secondary ht-text-sm">No invocations recorded.</p>;
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
        {invocations.map((inv, i) => (
          <tr key={i}>
            <td>{formatTimestamp(inv.execution_start_ts)}</td>
            <td>{formatDuration(inv.duration_ms)}</td>
            <td>
              <span class={`ht-tag ht-tag-${inv.status}`}>{inv.status}</span>
            </td>
            <td class="ht-text-secondary ht-text-sm">
              {inv.error_message ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
