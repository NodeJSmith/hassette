import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getHandlerInvocations } from "../../api/endpoints";
import type { ListenerData } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { formatDuration } from "../../utils/format";
import { HandlerInvocations } from "./handler-invocations";

interface Props {
  listener: ListenerData;
}

/**
 * Expandable handler row with lazy-loaded invocation history.
 *
 * Uses `useApi` with `lazy: true` so no API call is made until the row is
 * expanded. On re-expand, `refetch()` is called again — stale data stays
 * visible during the refresh (stale-while-revalidate).
 */
export function HandlerRow({ listener }: Props) {
  const lastInvoked = useRelativeTime(listener.last_invoked_at);
  const expanded = useRef(signal(false)).current;

  const { data: invocations, loading, refetch } = useApi(
    () => getHandlerInvocations(listener.listener_id),
    [listener.listener_id],
    { lazy: true },
  );

  const dotClass =
    listener.failed > 0 ? "danger" : listener.total_invocations > 0 ? "success" : "neutral";

  const toggle = () => {
    expanded.value = !expanded.value;
    if (expanded.value) {
      void refetch();
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
        onClick={toggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
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
          {lastInvoked && (
            <span class="ht-meta-item ht-text-muted">
              {lastInvoked}
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
          {loading.value && !invocations.value ? (
            <p class="ht-text-muted ht-text-xs">Loading invocations...</p>
          ) : invocations.value ? (
            <HandlerInvocations invocations={invocations.value} listenerId={listener.listener_id} />
          ) : null}
        </div>
      )}
    </div>
  );
}
