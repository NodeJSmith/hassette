import type { ListenerData } from "../../api/endpoints";
import { getListenerExecutions } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppState } from "../../state/context";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { formatDurationOrDash, formatOptionalDuration, lastDotSegment, MS_PER_SECOND } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { Chip } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import chipStyles from "./handler-chips.module.css";
import { HandlerDetailLayout } from "./handler-detail-layout";
import { listenerHealthKind } from "./handler-list";

function ModifierChips({ listener }: { listener: ListenerData }) {
  const chips: Array<{ label: string; value?: string }> = [];
  if (listener.debounce) chips.push({ label: "debounce", value: `${listener.debounce * MS_PER_SECOND}ms` });
  if (listener.throttle) chips.push({ label: "throttle", value: `${listener.throttle * MS_PER_SECOND}ms` });
  if (listener.once) chips.push({ label: "once" });
  if (listener.priority) chips.push({ label: "priority", value: String(listener.priority) });
  if (listener.immediate) chips.push({ label: "immediate" });
  if (listener.duration) chips.push({ label: "duration", value: `${listener.duration}s` });

  if (chips.length === 0) return null;
  return (
    <div class={chipStyles.chipRow} data-testid="modifier-chips">
      {chips.map((chip) => (
        <Chip key={chip.label} variant="modifier">
          {chip.label}
          {chip.value ? ` ${chip.value}` : ""}
        </Chip>
      ))}
    </div>
  );
}

function buildListenerStatsCells(listener: ListenerData, lastInvokedLabel: string): DetailStatsCell[] {
  const cells: DetailStatsCell[] = [
    { label: "Calls", value: listener.total_invocations },
    { label: "Successful", value: listener.successful },
    { label: "Last", value: listener.last_invoked_at ? lastInvokedLabel || "—" : "—" },
    {
      label: "Failed",
      value: listener.failed,
      tone: listener.failed > 0 ? "err" : undefined,
    },
    {
      label: "Timed Out",
      value: listener.timed_out,
      tone: listener.timed_out > 0 ? "warn" : undefined,
    },
  ];
  if (listener.cancelled > 0) cells.push({ label: "Cancelled", value: listener.cancelled });
  cells.push({ label: "Mode", value: listener.mode });
  if (listener.suppressed_count > 0) cells.push({ label: "Suppressed", value: listener.suppressed_count });
  if (listener.dropped_count > 0) cells.push({ label: "Dropped", value: listener.dropped_count });
  cells.push(
    { label: "Min", value: formatOptionalDuration(listener.min_duration_ms) },
    { label: "Avg", value: formatDurationOrDash(listener.avg_duration_ms) },
    { label: "Max", value: formatOptionalDuration(listener.max_duration_ms) },
  );
  return cells;
}

interface Props {
  listener: ListenerData;
  onSwitchToCode?: (line?: number) => void;
}

export function ListenerDetail({ listener, onSwitchToCode }: Props) {
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
    <HandlerDetailLayout
      testId={`listener-detail-${listener.listener_id}`}
      testIdPrefix="handler"
      kindLabel={kindLabel}
      statusKind={listenerKind}
      name={lastDotSegment(listener.handler_method)}
      subtitle={listener.human_description}
      registrationSource={listener.registration_source}
      chips={<ModifierChips listener={listener} />}
      sourceLocation={listener.source_location}
      onViewCode={onSwitchToCode}
      error={
        listenerKind === "err"
          ? {
              type: listener.last_error_type ?? null,
              message: listener.last_error_message ?? null,
              traceback: listener.last_error_traceback ?? null,
            }
          : null
      }
      statsCells={buildListenerStatsCells(listener, lastInvokedLabel)}
      statsTestId="handler-stats-row"
      executionHeading="invocations"
      executionRecords={executions ?? []}
      executionKind="handler"
      executionTableId={`invocation-table-${listener.listener_id}`}
      executionLoading={loading}
      executionHasData={executions !== undefined}
    />
  );
}
