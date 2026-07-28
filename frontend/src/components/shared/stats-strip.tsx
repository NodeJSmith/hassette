import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

import type { StatusKind } from "../../utils/status";

export interface StatsStripCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}

interface StatsStripProps {
  cells: StatsStripCell[];
  cols?: number;
  "data-testid"?: string;
}

const toneClass: Record<StatusKind, string> = {
  err: "text-destructive",
  warn: "text-[var(--status-warning)]",
  ok: "text-[var(--status-success)]",
  cancel: "text-[var(--status-cancel)]",
  mute: "text-muted-foreground",
};

function isZero(value: string | number): boolean {
  if (typeof value === "number") return value === 0;
  const n = parseFloat(value);
  return !isNaN(n) && n === 0;
}

export function StatsStrip({ cells, cols, "data-testid": testId }: StatsStripProps) {
  return (
    <div
      className="grid grid-cols-[repeat(var(--stats-cols,_7),minmax(0,1fr))] overflow-hidden rounded-md border border-[var(--border-strong)] bg-card shadow-md max-sidebar:grid-cols-4 max-mobile:grid-cols-3"
      style={cols ? ({ "--stats-cols": cols } as CSSProperties) : undefined}
      data-testid={testId}
    >
      {cells.map((c) => {
        const zero = isZero(c.value) && !c.tone;
        return (
          <div
            key={c.label}
            className="px-3.5 py-3 max-sidebar:px-2.5 max-sidebar:[&:nth-child(n+5)]:border-t max-sidebar:[&:nth-child(n+5)]:border-[var(--border-subtle)] max-mobile:[&:nth-child(n+4)]:border-t max-mobile:[&:nth-child(n+4)]:border-[var(--border-subtle)]"
            data-testid="stats-strip-cell"
          >
            <span
              className={cn(
                "block min-w-0 truncate font-mono text-xs uppercase tracking-[var(--text-label-tracking-wide)] text-muted-foreground max-sidebar:tracking-[var(--text-label-tracking)]",
                zero && "text-foreground-faint",
              )}
              data-testid="stats-strip-label"
            >
              {c.label}
            </span>
            <span
              className={cn(
                "mt-0 flex min-w-0 items-baseline gap-1.5 truncate font-sans text-[length:var(--text-stat)] leading-[var(--text-h1-leading)] font-medium text-foreground max-sidebar:text-[length:var(--text-h3)]",
                c.tone && toneClass[c.tone],
                zero && "text-foreground-faint",
              )}
              data-role="stats-strip-value"
              data-tone={c.tone ?? undefined}
            >
              {c.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}
