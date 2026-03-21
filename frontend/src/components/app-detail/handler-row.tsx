import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getHandlerInvocations } from "../../api/endpoints";
import type { ListenerData } from "../../api/endpoints";
import { formatDuration, formatRelativeTime } from "../../utils/format";
import { HandlerInvocations } from "./handler-invocations";

interface Props {
  listener: ListenerData;
}

/**
 * Expandable handler row with lazy-loaded invocation history.
 *
 * THE KEY ARCHITECTURAL WIN: `expanded` and `loaded` are LOCAL signals,
 * not props from the parent. A parent re-render (from WS update) does NOT
 * reset these signals — the row stays expanded with its cached data.
 */
export function HandlerRow({ listener }: Props) {
  // Local signals — survive parent re-renders
  const expanded = useRef(signal(false)).current;
  const loaded = useRef(signal(false)).current;
  const invocations = useRef(signal<unknown[]>([])).current;
  const loading = useRef(signal(false)).current;

  const toggle = async () => {
    expanded.value = !expanded.value;
    if (expanded.value && !loaded.value) {
      loading.value = true;
      try {
        invocations.value = await getHandlerInvocations(listener.listener_id);
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
        data-testid={`handler-row-${listener.listener_id}`}
      >
        <td class="ht-item-row-toggle">{expanded.value ? "▾" : "▸"}</td>
        <td>
          <code class="ht-text-sm">{listener.handler_method}</code>
          <div class="ht-text-secondary ht-text-xs">{listener.handler_summary}</div>
        </td>
        <td class="ht-text-mono">{listener.total_invocations}</td>
        <td class="ht-text-mono">{listener.failed}</td>
        <td>{formatDuration(listener.avg_duration_ms)}</td>
        <td class="ht-text-secondary">
          {listener.last_invoked_at ? formatRelativeTime(listener.last_invoked_at) : "—"}
        </td>
      </tr>
      {expanded.value && (
        <tr class="ht-item-row-detail">
          <td colSpan={6}>
            {loading.value ? (
              <p class="ht-text-secondary">Loading invocations...</p>
            ) : (
              <HandlerInvocations invocations={invocations.value as never[]} />
            )}
          </td>
        </tr>
      )}
    </>
  );
}
