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

export function StatsStrip({ cells, cols, "data-testid": testId }: StatsStripProps) {
  return (
    <div
      class="ht-stats-strip"
      style={cols ? `--stats-cols: ${cols}` : undefined}
      data-testid={testId}
    >
      {cells.map((c) => (
        <div key={c.label} class="ht-stats-strip__cell">
          <span class="ht-stats-strip__label">{c.label}</span>
          <span class={`ht-stats-strip__value${c.tone ? ` ht-stats-strip__value--${c.tone}` : ""}`}>
            {c.value}
          </span>
        </div>
      ))}
    </div>
  );
}
