import type { ListenerData } from "../../api/endpoints";
import { getListenerExecutions } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppState } from "../../state/context";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { lastDotSegment, MS_PER_SECOND } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { Chip } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import { DetailStats } from "../shared/detail-stats";
import { ErrorBanner } from "../shared/error-banner";
import { DetailHeader } from "./detail-header";
import { ExecutionSection } from "./execution-section";
import chipStyles from "./handler-chips.module.css";
import { HandlerDetailLayout } from "./handler-detail-layout";
import { listenerHealthKind } from "./handler-list";
import { HandlerModeChip } from "./handler-mode-chip";
import { RegistrationFooter } from "./registration-footer";
import { buildCommonStatCells, type CommonStatInput } from "./stat-cell-builders";

function ModifierChips({ listener }: { listener: ListenerData }) {
  const chips: Array<{ label: string; value?: string }> = [];
  if (listener.debounce) chips.push({ label: "debounce", value: `${listener.debounce * MS_PER_SECOND}ms` });
  if (listener.throttle) chips.push({ label: "throttle", value: `${listener.throttle * MS_PER_SECOND}ms` });
  if (listener.once) chips.push({ label: "once" });
  if (listener.priority) chips.push({ label: "priority", value: String(listener.priority) });
  if (listener.immediate) chips.push({ label: "immediate" });
  if (listener.duration) chips.push({ label: "duration", value: `${listener.duration}s` });
  if (listener.backpressure === "drop_newest") chips.push({ label: "backpressure", value: "drop_newest" });

  return (
    <div class={chipStyles.chipRow} data-testid="modifier-chips">
      <HandlerModeChip mode={listener.mode} />
      {chips.map((chip) => (
        <Chip key={chip.label} variant="listener">
          {chip.label}
          {chip.value ? ` ${chip.value}` : ""}
        </Chip>
      ))}
    </div>
  );
}

function buildListenerStatsCells(listener: ListenerData, lastInvokedLabel: string): DetailStatsCell[] {
  const input: CommonStatInput = {
    totalLabel: "Calls",
    total: listener.total_invocations,
    failed: listener.failed,
    avgDurationMs: listener.avg_duration_ms,
    lastLabel: listener.last_invoked_at ? lastInvokedLabel || "—" : "—",
    timedOut: listener.timed_out,
    cancelled: listener.cancelled,
    threadLeaked: listener.thread_leaked,
    suppressedCount: listener.suppressed_count,
    droppedCount: listener.dropped_count,
  };
  const cells = buildCommonStatCells(input);
  if (listener.backpressure_dropped_count > 0) {
    const dropped = listener.backpressure_dropped_count;
    const attempted = listener.total_invocations + dropped;
    const pct = Math.round((100 * dropped) / attempted);
    cells.push({ label: "Backpressure Dropped", value: `${dropped} (${pct}%)`, tone: "warn" });
  }
  return cells;
}

interface Props {
  listener: ListenerData;
  appKey: string;
  instanceQs?: string;
  onSwitchToCode?: (line?: number) => void;
}

export function ListenerDetail({ listener, appKey, instanceQs, onSwitchToCode }: Props) {
  const { data: executions, isPending: loading } = useScopedQuery(
    queryKeys.listenerExecutions(listener.listener_id),
    (since, signal) => getListenerExecutions(listener.listener_id, DETAIL_FETCH_LIMIT, since, signal),
  );

  const { executionCompleted } = useAppState();
  const lastInvokedLabel = useRelativeTime(listener.last_invoked_at ?? null);

  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.kind === "handler" && e.listener_id === listener.listener_id) ?? false,
    queryKeys.listenerExecutions(listener.listener_id),
  );

  const kindLabel = handlerKindLabel("listener", listener.listener_kind, null);
  const listenerKind = listenerHealthKind(listener);

  return (
    <HandlerDetailLayout testId={`listener-detail-${listener.listener_id}`}>
      <DetailHeader
        name={lastDotSegment(listener.handler_method)}
        kindLabel={kindLabel}
        statusKind={listenerKind}
        kind="handler"
        subtitle={listener.human_description}
      />

      <ModifierChips listener={listener} />

      {listenerKind === "err" && (listener.last_error_message || listener.last_error_type) && (
        <ErrorBanner
          errorType={listener.last_error_type ?? null}
          errorMessage={listener.last_error_message ?? null}
          traceback={listener.last_error_traceback ?? null}
          data-testid="handler-error-banner"
        />
      )}

      <DetailStats cells={buildListenerStatsCells(listener, lastInvokedLabel)} data-testid="handler-stats-row" />

      <ExecutionSection
        heading="invocations"
        records={executions}
        kind="handler"
        tableId={`invocation-table-${listener.listener_id}`}
        loading={loading}
        appKey={appKey}
        handlerKind="listener"
        handlerId={listener.listener_id}
        instanceQs={instanceQs}
      />

      <RegistrationFooter
        kind="handler"
        testId={`listener-detail-${listener.listener_id}`}
        sourceLocation={listener.source_location}
        registrationSource={listener.registration_source}
        onViewCode={onSwitchToCode}
      />
    </HandlerDetailLayout>
  );
}
