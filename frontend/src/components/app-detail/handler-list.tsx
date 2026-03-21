import type { ListenerData } from "../../api/endpoints";
import { HandlerRow } from "./handler-row";

interface Props {
  listeners: ListenerData[] | null;
}

export function HandlerList({ listeners }: Props) {
  if (!listeners) return null;
  if (listeners.length === 0) {
    return <p class="ht-text-secondary">No handlers registered.</p>;
  }

  return (
    <table class="ht-table">
      <thead>
        <tr>
          <th style={{ width: "24px" }} />
          <th>Handler</th>
          <th>Invocations</th>
          <th>Errors</th>
          <th>Avg Duration</th>
          <th>Last Fired</th>
        </tr>
      </thead>
      <tbody>
        {listeners.map((ls) => (
          <HandlerRow key={ls.listener_id} listener={ls} />
        ))}
      </tbody>
    </table>
  );
}
