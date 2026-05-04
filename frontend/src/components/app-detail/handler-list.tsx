import type { ListenerData, JobData } from "../../api/endpoints";
import { UnifiedHandlerRow, type UnifiedItem, type UnifiedItemKind } from "./unified-handler-row";
import { statusToKind } from "../../utils/status";
import { computeHandlerStats } from "../../utils/handler-stats";

export interface SelectedHandlerId {
  kind: UnifiedItemKind;
  id: number;
}

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  selectedId: SelectedHandlerId | null;
  onSelect: (id: SelectedHandlerId) => void;
}

function listenerStatusKind(l: ListenerData) {
  if (l.failed > 0 || l.timed_out > 0) return statusToKind("failed");
  if (l.total_invocations > 0) return statusToKind("running");
  return statusToKind("stopped");
}

function jobStatusKind(j: JobData) {
  if (j.cancelled) return statusToKind("disabled");
  if (j.failed > 0 || j.timed_out > 0) return statusToKind("failed");
  if (j.total_executions > 0) return statusToKind("running");
  return statusToKind("stopped");
}

function buildItems(listeners: ListenerData[], jobs: JobData[]): UnifiedItem[] {
  const listenerItems: UnifiedItem[] = listeners.map((l) => ({
    kind: "listener" as const,
    id: l.listener_id,
    name: l.handler_method.split(".").pop() ?? l.handler_method,
    humanDescription: l.human_description ?? null,
    statusKind: listenerStatusKind(l),
    data: l,
  }));

  const jobItems: UnifiedItem[] = jobs.map((j) => ({
    kind: "job" as const,
    id: j.job_id,
    name: j.job_name,
    humanDescription: j.trigger_label !== "" ? j.trigger_label : null,
    statusKind: jobStatusKind(j),
    data: j,
  }));

  // Listeners first, then jobs
  return [...listenerItems, ...jobItems];
}

export function HandlerList({ listeners, jobs, selectedId, onSelect }: Props) {
  if (listeners.length === 0 && jobs.length === 0) return null;

  const items = buildItems(listeners, jobs);

  const { totalFailed, totalTimedOut, totalInvocations, totalExecutions } =
    computeHandlerStats(listeners, jobs);

  return (
    <div>
      <div class="ht-stats-strip" data-testid="stats-strip">
        <span class="ht-stats-strip__item">
          <strong>{items.length}</strong> handler{items.length !== 1 ? "s" : ""}
        </span>
        <span class="ht-stats-strip__item">
          {totalInvocations + totalExecutions} calls/runs
        </span>
        {totalFailed > 0 && (
          <span class="ht-stats-strip__item ht-stats-strip__item--err">
            {totalFailed} failed
          </span>
        )}
        {totalTimedOut > 0 && (
          <span class="ht-stats-strip__item ht-stats-strip__item--warn">
            {totalTimedOut} timed out
          </span>
        )}
      </div>
      <div class="ht-item-list" data-testid="handler-list">
        {items.map((item) => (
          <UnifiedHandlerRow
            key={`${item.kind}-${item.id}`}
            item={item}
            isSelected={
              selectedId !== null &&
              selectedId.kind === item.kind &&
              selectedId.id === item.id
            }
            onSelect={() => onSelect({ kind: item.kind, id: item.id })}
          />
        ))}
      </div>
    </div>
  );
}
