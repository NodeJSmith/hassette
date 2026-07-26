import { formatDurationOrDash, formatRate } from "../../utils/format";
import type { DetailStatsCell } from "../shared/detail-stats";

/** Number of fixed cells `buildCommonStatCells` always produces, before any conditional cells. */
export const COMMON_STAT_CELL_COUNT = 5;

export interface CommonStatInput {
  totalLabel: string;
  total: number;
  failed: number;
  avgDurationMs: number | null;
  lastLabel: string;
  /** Label for the "last" cell — defaults to "Last"; job passes "Next" when showing next-run/fire-at text. */
  lastFieldLabel?: string;
  timedOut: number;
  cancelled: number;
  threadLeaked: number;
  suppressedCount: number;
  droppedCount: number;
  /**
   * Extra cell placed right after "Cancelled" if it renders, else right after
   * "Timed Out" if it renders, else at the start of the conditional zone.
   * Callers never compute this position themselves — the builder owns both
   * the cell labels and the insertion point. Only `JobDetail`'s "Skipped"
   * cell needs this today.
   */
  extraCell?: DetailStatsCell;
}

/** Index at which to splice `extraCell` into `cells`, per the rule documented on `CommonStatInput.extraCell`. */
function resolveExtraCellIndex(cells: DetailStatsCell[]): number {
  const cancelledIndex = cells.findIndex((cell) => cell.label === "Cancelled");
  if (cancelledIndex >= 0) return cancelledIndex + 1;

  const timedOutIndex = cells.findIndex((cell) => cell.label === "Timed Out");
  if (timedOutIndex >= 0) return timedOutIndex + 1;

  return COMMON_STAT_CELL_COUNT;
}

export function buildCommonStatCells(input: CommonStatInput): DetailStatsCell[] {
  const cells: DetailStatsCell[] = [
    { label: input.totalLabel, value: input.total },
    { label: "Failed", value: input.failed, tone: input.failed > 0 ? "err" : undefined },
    {
      label: "Err %",
      value: formatRate(input.failed, input.total),
      tone: input.failed > 0 ? "err" : undefined,
    },
    { label: "Avg", value: formatDurationOrDash(input.avgDurationMs) },
    { label: input.lastFieldLabel ?? "Last", value: input.lastLabel },
  ];
  if (input.timedOut > 0) cells.push({ label: "Timed Out", value: input.timedOut, tone: "warn" });
  if (input.cancelled > 0) cells.push({ label: "Cancelled", value: input.cancelled, tone: "cancel" });
  if (input.extraCell) cells.splice(resolveExtraCellIndex(cells), 0, input.extraCell);
  if (input.threadLeaked > 0) cells.push({ label: "Thread Leaked", value: input.threadLeaked, tone: "warn" });
  if (input.suppressedCount > 0) cells.push({ label: "Suppressed", value: input.suppressedCount, tone: "mute" });
  if (input.droppedCount > 0) cells.push({ label: "Dropped", value: input.droppedCount, tone: "warn" });
  return cells;
}
