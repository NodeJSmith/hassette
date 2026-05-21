import clsx from "clsx";

import type { StatusKind } from "../../utils/status";
import styles from "./stats-strip.module.css";

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

const toneClass: Partial<Record<StatusKind, string>> = {
  err: styles.valueErr,
  warn: styles.valueWarn,
  ok: styles.valueOk,
  mute: styles.valueMute,
};

export function StatsStrip({ cells, cols, "data-testid": testId }: StatsStripProps) {
  return (
    <div class={styles.strip} style={cols ? `--stats-cols: ${cols}` : undefined} data-testid={testId}>
      {cells.map((c) => (
        <div key={c.label} class={styles.cell} data-testid="stats-strip-cell">
          <span class={styles.label} data-testid="stats-strip-label">
            {c.label}
          </span>
          <span class={clsx(styles.value, c.tone && toneClass[c.tone])} data-tone={c.tone ?? undefined}>
            {c.value}
          </span>
        </div>
      ))}
    </div>
  );
}
