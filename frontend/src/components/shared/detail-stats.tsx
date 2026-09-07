import { cn } from "@/lib/utils";

import type { StatusKind } from "../../utils/status";

export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}

// Intentionally not app-detail's SECTION_LABEL_CLASS, which this matches except for its
// leading "mb-2". These are stat values inside a gap-1 flex column that already supplies the
// spacing, and shared/ must not depend on app-detail/.
const STAT_VALUE_CLASS = "font-sans text-[length:var(--text-h3)] font-semibold text-foreground";

const toneClass: Record<StatusKind, string> = {
  err: "text-destructive",
  warn: "text-[var(--status-warning)]",
  ok: "text-[var(--status-success)]",
  cancel: "text-[var(--status-cancel)]",
  mute: "text-muted-foreground",
};

interface DetailStatsProps {
  cells: DetailStatsCell[];
  "data-testid"?: string;
}

export function DetailStats({ cells, "data-testid": testId }: DetailStatsProps) {
  return (
    <div className="mb-4 flex flex-wrap gap-6 border-y border-border py-3" data-testid={testId}>
      {cells.map((cell) => (
        <div
          className="flex min-w-14 flex-col gap-1"
          key={cell.label}
          data-testid={testId ? `${testId}-cell` : undefined}
        >
          <span className="whitespace-nowrap text-xs font-medium uppercase tracking-[var(--text-label-tracking)] text-muted-foreground">
            {cell.label}
          </span>
          <span className={cn(STAT_VALUE_CLASS, cell.tone && toneClass[cell.tone])} data-tone={cell.tone}>
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
