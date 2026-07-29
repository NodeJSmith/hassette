import type { JobData, ListenerData } from "../../api/endpoints";
import { formatTriggerDetail, lastDotSegment } from "../../utils/format";
import { statusToKind } from "../../utils/status";
import { compareFailingFirst } from "./handler-sort";
import { UnifiedHandlerRow, type UnifiedItem, type UnifiedItemKind } from "./unified-handler-row";

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

function healthKindFromCounts(failed: number, timedOut: number, total: number) {
  if (failed > 0 || timedOut > 0) return statusToKind("failed");
  if (total > 0) return statusToKind("running");
  return statusToKind("stopped");
}

export function listenerHealthKind(l: ListenerData) {
  return healthKindFromCounts(l.failed, l.timed_out, l.total_invocations);
}

export function jobHealthKind(j: JobData) {
  return healthKindFromCounts(j.failed, j.timed_out, j.total_executions);
}

export function buildItems(listeners: ListenerData[], jobs: JobData[]): UnifiedItem[] {
  const listenerItems: UnifiedItem[] = listeners.map((listener) => ({
    kind: "listener" as const,
    id: listener.listener_id,
    name: lastDotSegment(listener.handler_method),
    humanDescription: listener.human_description ?? null,
    statusKind: listenerHealthKind(listener),
    data: listener,
  }));

  const jobItems: UnifiedItem[] = jobs.map((job) => {
    const parts = [job.trigger_label || null, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null];
    const humanDescription = parts.filter(Boolean).join(" ") || null;
    return {
      kind: "job" as const,
      id: job.job_id,
      name: job.job_name,
      humanDescription,
      statusKind: jobHealthKind(job),
      data: job,
    };
  });

  const items = [...listenerItems, ...jobItems];

  // Surface exceptions first, while stable sorting preserves registration order within each health group.
  return items.sort(compareFailingFirst);
}

export function HandlerList({ listeners, jobs, selectedId, onSelect }: Props) {
  if (listeners.length === 0 && jobs.length === 0) return null;

  const items = buildItems(listeners, jobs);

  return (
    <div>
      <div
        className="overflow-hidden rounded-md border border-strong [box-shadow:var(--shadow-2)]"
        data-testid="handler-list"
      >
        {items.map((item) => (
          <UnifiedHandlerRow
            key={`${item.kind}-${item.id}`}
            item={item}
            isSelected={selectedId !== null && selectedId.kind === item.kind && selectedId.id === item.id}
            onSelect={() => onSelect({ kind: item.kind, id: item.id })}
          />
        ))}
      </div>
    </div>
  );
}
