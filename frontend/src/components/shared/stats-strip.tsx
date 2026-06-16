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

const toneClass: Record<StatusKind, string> = {
  err: styles.valueErr,
  warn: styles.valueWarn,
  ok: styles.valueOk,
  cancel: styles.valueCancel,
  mute: styles.valueMute,
};

function isZero(value: string | number): boolean {
  if (typeof value === "number") return value === 0;
  const n = parseFloat(value);
  return !isNaN(n) && n === 0;
}

export function StatsStrip({ cells, cols, "data-testid": testId }: StatsStripProps) {
  return (
    <div class={styles.strip} style={cols ? `--stats-cols: ${cols}` : undefined} data-testid={testId}>
      {cells.map((c) => {
        const zero = isZero(c.value) && !c.tone;
        return (
          <div key={c.label} class={clsx(styles.cell, zero && styles.zeroCell)} data-testid="stats-strip-cell">
            <span class={styles.label} data-testid="stats-strip-label">
              {c.label}
            </span>
            <span class={clsx(styles.value, c.tone && toneClass[c.tone])} data-tone={c.tone ?? undefined}>
              {c.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}
