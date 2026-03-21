import type { ListenerData } from "../../api/endpoints";
import { HandlerRow } from "./handler-row";

interface Props {
  listeners: ListenerData[] | null;
}

export function HandlerList({ listeners }: Props) {
  if (!listeners) return null;
  if (listeners.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No event handlers registered.</p>;
  }

  return (
    <div class="ht-item-list">
      {listeners.map((ls) => (
        <HandlerRow key={ls.listener_id} listener={ls} />
      ))}
    </div>
  );
}
