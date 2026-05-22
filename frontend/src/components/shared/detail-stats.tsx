import clsx from "clsx";

import type { StatusKind } from "../../utils/status";
import styles from "./detail-stats.module.css";

export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}

const toneClass: Record<StatusKind, string> = {
  err: styles.valueErr,
  warn: styles.valueWarn,
  ok: styles.valueOk,
  mute: styles.valueMute,
};

interface DetailStatsProps {
  cells: DetailStatsCell[];
  "data-testid"?: string;
}

export function DetailStats({ cells, "data-testid": testId }: DetailStatsProps) {
  return (
    <div class={styles.row} data-testid={testId}>
      {cells.map((cell) => (
        <div class={styles.cell} key={cell.label} data-testid={testId ? `${testId}-cell` : undefined}>
          <span class={styles.label}>{cell.label}</span>
          <span class={clsx(styles.value, cell.tone && toneClass[cell.tone])} data-tone={cell.tone}>
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
