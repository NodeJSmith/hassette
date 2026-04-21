import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getHandlerInvocations } from "../../api/endpoints";
import type { ListenerData } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { formatDuration, pluralize } from "../../utils/format";
import { HandlerInvocations } from "./handler-invocations";

interface Props {
  listener: ListenerData;
}

/**
 * Expandable handler row with lazy-loaded invocation history.
 *
 * Uses `useScopedApi` with `lazy: true` so no API call is made until the row is
 * expanded. On re-expand, `refetch()` is called again — stale data stays
 * visible during the refresh (stale-while-revalidate).
 */
export function HandlerRow({ listener }: Props) {
  const lastInvoked = useRelativeTime(listener.last_invoked_at ?? null);
  const expanded = useRef(signal(false)).current;

  const { data: invocations, loading, refetch } = useScopedApi(
    (sid) => getHandlerInvocations(listener.listener_id, 50, sid),
    { deps: [listener.listener_id], lazy: true },
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
      class={`ht-item-row${expanded.value ? " is-expanded" : ""}`}
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
          <span class="ht-item-row__subtitle" title={`${listener.handler_method} · ${listener.topic}`}>
            {shortName} · <span class="ht-text-mono">{listener.topic}</span>
          </span>
        </div>
        <div class="ht-item-row__stats">
          <span class="ht-meta-item" title="Total invocations">
            {pluralize(listener.total_invocations, "call")}
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
          {(listener.immediate || listener.duration || listener.entity_id || listener.once || listener.debounce || listener.throttle) && (
            <div class="ht-tag-row" data-testid="listener-options">
              {listener.entity_id && (
                <span class="ht-tag ht-tag--neutral" title="Entity ID">{listener.entity_id}</span>
              )}
              {!!listener.immediate && <span class="ht-tag ht-tag--neutral">immediate</span>}
              {listener.duration !== null && (
                <span class="ht-tag ht-tag--neutral" title="Duration hold">duration: {listener.duration}s</span>
              )}
              {!!listener.once && <span class="ht-tag ht-tag--neutral">once</span>}
              {listener.debounce !== null && (
                <span class="ht-tag ht-tag--neutral" title="Debounce">debounce: {listener.debounce}s</span>
              )}
              {listener.throttle !== null && (
                <span class="ht-tag ht-tag--neutral" title="Throttle">throttle: {listener.throttle}s</span>
              )}
            </div>
          )}
          {(listener.source_location || listener.registration_source) && (
            <div class="ht-source-display" data-testid="source-display">
              {listener.source_location && (
                <div class="ht-source-display__location">{listener.source_location}</div>
              )}
              {listener.registration_source && (
                <code class="ht-source-display__code">{listener.registration_source}</code>
              )}
            </div>
          )}
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
