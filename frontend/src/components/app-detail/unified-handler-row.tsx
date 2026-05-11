import { StatusShape } from "../shared/status-shape";
import type { StatusKind } from "../../utils/status";
import { handlerKindLabel } from "../../utils/status";
import type { ListenerData, JobData } from "../../api/endpoints";
import { pluralize, formatRelativeTime, formatTimestamp } from "../../utils/format";

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

const KIND_GLYPHS: Record<string, string> = {
  "state change": "◇",
  "service call": "▷",
  "cron": "↻", "interval": "↻", "every": "↻", "daily": "↻",
  "once": "↻", "after": "↻", "schedule": "↻",
};

function kindGlyph(label: string): string {
  return KIND_GLYPHS[label] ?? "◆";
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
  let chipLabel: string;
  let isFailing: boolean;
  let lastErrorMessage: string | null = null;
  let nextRunLabel: string | null = null;
  let nextRunTitle: string | null = null;

  if (item.kind === "listener") {
    const l = item.data;
    chipLabel = handlerKindLabel("listener", l.listener_kind, null);
    invocationsOrRuns = l.total_invocations;
    failed = l.failed;
    timedOut = l.timed_out;
    isFailing = failed > 0 || timedOut > 0;
    lastErrorMessage = isFailing ? (l.last_error_message ?? null) : null;
  } else {
    const j = item.data;
    chipLabel = handlerKindLabel("job", null, j.trigger_type);
    invocationsOrRuns = j.total_executions;
    failed = j.failed;
    timedOut = j.timed_out;
    isFailing = failed > 0 || timedOut > 0;
    // Next-run line for schedule jobs
    if (j.next_run) {
      nextRunLabel = `next ${formatRelativeTime(j.next_run)}`;
      nextRunTitle = formatTimestamp(j.next_run);
    } else if (j.fire_at) {
      nextRunLabel = `fire at ${formatRelativeTime(j.fire_at)}`;
      nextRunTitle = formatTimestamp(j.fire_at);
    }
  }

  const callLabel = item.kind === "listener" ? "call" : "run";
  const glyph = kindGlyph(chipLabel);

  return (
    <button
      type="button"
      class={`ht-unified-row${isSelected ? " ht-unified-row--selected" : ""}`}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      aria-pressed={isSelected}
      aria-label={`${item.name}${item.humanDescription ? ": " + item.humanDescription : ""}`}
      onClick={onSelect}
    >
      <span class="ht-unified-row__status" aria-hidden="true">
        <StatusShape kind={item.statusKind} size={10} />
      </span>
      <span class="ht-unified-row__kind-glyph" aria-hidden="true">{glyph}</span>
      <div class="ht-unified-row__body">
        <div class="ht-unified-row__header">
          <span class="ht-unified-row__kind-chip" aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </span>
          <span class="ht-unified-row__name">{item.name}</span>
          {isFailing && (
            <span class="ht-badge ht-badge--danger ht-badge--xs">failing</span>
          )}
        </div>
        {/* Subline: error message (when failing) or human description (otherwise) */}
        {isFailing && lastErrorMessage ? (
          <span class="ht-unified-row__subline--err" title={lastErrorMessage}>
            {lastErrorMessage}
          </span>
        ) : item.humanDescription ? (
          <span class="ht-unified-row__desc">{item.humanDescription}</span>
        ) : null}
        {/* Next-run line for schedule jobs */}
        {nextRunLabel !== null && (
          <span class="ht-unified-row__next-run" title={nextRunTitle ?? undefined}>{nextRunLabel}</span>
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
      </div>
    </button>
  );
}
