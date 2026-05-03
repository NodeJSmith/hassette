import { StatusShape } from "../shared/status-shape";
import type { StatusKind } from "../../utils/status";
import { handlerKindLabel } from "../../utils/status";
import type { ListenerData, JobData } from "../../api/endpoints";
import { pluralize } from "../../utils/format";

export type UnifiedItemKind = "listener" | "job";

/** Discriminated union for items that can appear in the unified list. */
export type UnifiedItem =
  | { kind: "listener"; id: number; name: string; humanDescription: string | null; statusKind: StatusKind; data: ListenerData }
  | { kind: "job"; id: number; name: string; humanDescription: string | null; statusKind: StatusKind; data: JobData };

interface Props {
  item: UnifiedItem;
  isSelected: boolean;
  onSelect: () => void;
}

/**
 * A single row in the unified handlers+jobs master list.
 *
 * Clicking the row selects it in the detail pane (no expand-in-place).
 * The kind chip visually distinguishes handlers vs jobs.
 */
export function UnifiedHandlerRow({ item, isSelected, onSelect }: Props) {
  let invocationsOrRuns: number;
  let failed: number;
  let timedOut: number;
  let lastErrorPreview: string | null = null;
  let chipLabel: string;

  if (item.kind === "listener") {
    const l = item.data;
    chipLabel = handlerKindLabel("listener", l.topic, null);
    invocationsOrRuns = l.total_invocations;
    failed = l.failed;
    timedOut = l.timed_out;
    lastErrorPreview = (failed > 0 || timedOut > 0) ? (l.last_error_message ?? null) : null;
  } else {
    const j = item.data;
    chipLabel = handlerKindLabel("job", null, j.trigger_type);
    invocationsOrRuns = j.total_executions;
    failed = j.failed;
    timedOut = j.timed_out;
  }

  const callLabel = item.kind === "listener" ? "call" : "run";

  return (
    <div
      class={`ht-unified-row${isSelected ? " ht-unified-row--selected" : ""}`}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      aria-label={`${item.name}${item.humanDescription ? ": " + item.humanDescription : ""}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <span class="ht-unified-row__status" aria-hidden="true">
        <StatusShape kind={item.statusKind} size={10} />
      </span>
      <div class="ht-unified-row__body">
        <div class="ht-unified-row__header">
          <span class="ht-unified-row__kind-chip" aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </span>
          <span class="ht-unified-row__name">{item.name}</span>
        </div>
        {item.humanDescription && (
          <span class="ht-unified-row__desc">{item.humanDescription}</span>
        )}
        <div class="ht-unified-row__stats">
          <span title={`Total ${callLabel}s`}>{pluralize(invocationsOrRuns, callLabel)}</span>
          {failed > 0 && (
            <span class="ht-unified-row__stats--err">{failed} failed</span>
          )}
          {timedOut > 0 && (
            <span class="ht-unified-row__stats--warn">{timedOut} timed out</span>
          )}
        </div>
        {lastErrorPreview && (
          <span class="ht-unified-row__error-preview" title={lastErrorPreview}>
            {lastErrorPreview}
          </span>
        )}
      </div>
    </div>
  );
}
