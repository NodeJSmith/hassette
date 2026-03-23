import type { ListenerData } from "../../api/endpoints";
import { HandlerRow } from "./handler-row";

interface Props {
  listeners: ListenerData[] | null;
}

export function HandlerList({ listeners }: Props) {
  if (!listeners) return null;
  if (listeners.length === 0) return null;

  return (
    <div class="ht-item-list" data-testid="handler-list">
      {listeners.map((ls) => (
        <HandlerRow key={ls.listener_id} listener={ls} />
      ))}
    </div>
  );
}
