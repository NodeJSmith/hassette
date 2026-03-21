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
    return <p class="ht-text-muted ht-text-xs">No invocations recorded.</p>;
  }

  return (
    <table class="ht-table ht-table--compact">
      <thead>
        <tr>
          <th>Status</th>
          <th>Timestamp</th>
          <th>Duration</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {invocations.map((inv, i) => (
          <tr key={i}>
            <td>
              <span class={`ht-badge ht-badge--sm ht-badge--${inv.status === "success" ? "success" : "danger"}`}>{inv.status}</span>
            </td>
            <td class="ht-text-mono ht-text-xs">{formatTimestamp(inv.execution_start_ts)}</td>
            <td>{formatDuration(inv.duration_ms)}</td>
            <td class="ht-text-secondary ht-text-sm">
              {inv.error_message ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
