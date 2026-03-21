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
  const expanded = useRef(signal(false)).current;
  const loaded = useRef(signal(false)).current;
  const invocations = useRef(signal<unknown[]>([])).current;
  const loading = useRef(signal(false)).current;

  const dotClass =
    listener.failed > 0 ? "danger" : listener.total_invocations > 0 ? "success" : "neutral";

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

  // Extract short method name from fully-qualified path
  const parts = listener.handler_method.split(".");
  const shortName = parts[parts.length - 1];

  return (
    <div
      class="ht-item-row"
      data-testid={`handler-row-${listener.listener_id}`}
    >
      <div
        class="ht-item-row__main"
        role="button"
        tabIndex={0}
        aria-expanded={expanded.value}
        onClick={() => void toggle()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void toggle(); } }}
      >
        <span class={`ht-item-row__dot ht-item-row__dot--${dotClass}`} />
        <div class="ht-item-row__content">
          <span class="ht-item-row__title">{listener.handler_summary || shortName}</span>
          <span class="ht-item-row__subtitle">
            {listener.handler_method} · {listener.topic}
          </span>
        </div>
        <div class="ht-item-row__stats">
          <span class="ht-meta-item" title="Total invocations">
            {listener.total_invocations} calls
          </span>
          {listener.failed > 0 && (
            <span class="ht-meta-item--strong ht-text-danger">{listener.failed} failed</span>
          )}
          {listener.avg_duration_ms > 0 && (
            <span class="ht-meta-item">{formatDuration(listener.avg_duration_ms)} avg</span>
          )}
          {listener.last_invoked_at && (
            <span class="ht-meta-item ht-text-muted">
              {formatRelativeTime(listener.last_invoked_at)}
            </span>
          )}
        </div>
        <span class={`ht-item-row__chevron${expanded.value ? " is-open" : ""}`}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 2 8 6 4 10" />
          </svg>
        </span>
      </div>
      {expanded.value && (
        <div class="ht-item-detail" id={`handler-${listener.listener_id}-detail`}>
          {loading.value ? (
            <p class="ht-text-muted ht-text-xs">Loading invocations...</p>
          ) : (
            <HandlerInvocations invocations={invocations.value as never[]} listenerId={listener.listener_id} />
          )}
        </div>
      )}
    </div>
  );
}
