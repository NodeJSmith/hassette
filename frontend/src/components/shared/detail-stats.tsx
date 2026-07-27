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
  cancel: styles.valueCancel,
  mute: styles.valueMute,
};

interface DetailStatsProps {
  cells: DetailStatsCell[];
  "data-testid"?: string;
}

export function DetailStats({ cells, "data-testid": testId }: DetailStatsProps) {
  return (
    <div className={styles.row} data-testid={testId}>
      {cells.map((cell) => (
        <div className={styles.cell} key={cell.label} data-testid={testId ? `${testId}-cell` : undefined}>
          <span className={styles.label}>{cell.label}</span>
          <span className={clsx(styles.value, cell.tone && toneClass[cell.tone])} data-tone={cell.tone}>
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
