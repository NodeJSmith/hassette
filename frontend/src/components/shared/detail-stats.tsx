import { cn } from "@/lib/utils";

import type { StatusKind } from "../../utils/status";

export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}

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
          <span
            className={cn(
              "font-sans text-[length:var(--text-h3)] font-semibold text-foreground",
              cell.tone && toneClass[cell.tone],
            )}
            data-tone={cell.tone}
          >
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
