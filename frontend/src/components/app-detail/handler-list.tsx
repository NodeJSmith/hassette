import type { ListenerData, JobData } from "../../api/endpoints";
import { UnifiedHandlerRow, type UnifiedItem, type UnifiedItemKind } from "./unified-handler-row";
import { statusToKind } from "../../utils/status";
import { formatTriggerDetail, lastDotSegment } from "../../utils/format";
import styles from "./handler-list.module.css";

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

export function listenerStatusKind(l: ListenerData) {
  if (l.failed > 0 || l.timed_out > 0) return statusToKind("failed");
  if (l.total_invocations > 0) return statusToKind("running");
  return statusToKind("stopped");
}

export function jobStatusKind(j: JobData) {
  if (j.failed > 0 || j.timed_out > 0) return statusToKind("failed");
  if (j.total_executions > 0) return statusToKind("running");
  return statusToKind("stopped");
}

export function buildItems(listeners: ListenerData[], jobs: JobData[]): UnifiedItem[] {
  const listenerItems: UnifiedItem[] = listeners.map((listener) => ({
    kind: "listener" as const,
    id: listener.listener_id,
    name: lastDotSegment(listener.handler_method),
    humanDescription: listener.human_description ?? null,
    statusKind: listenerStatusKind(listener),
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
      statusKind: jobStatusKind(job),
      data: job,
    };
  });

  // Listeners first, then jobs
  return [...listenerItems, ...jobItems];
}

export function HandlerList({ listeners, jobs, selectedId, onSelect }: Props) {
  if (listeners.length === 0 && jobs.length === 0) return null;

  const items = buildItems(listeners, jobs);

  return (
    <div>
      <div class={styles.itemList} data-testid="handler-list">
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
