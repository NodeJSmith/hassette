import clsx from "clsx";

import styles from "./detail-stats.module.css";

export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: "err" | "warn";
}

interface Props {
  cells: DetailStatsCell[];
  "data-testid"?: string;
}

export function DetailStats({ cells, "data-testid": testId }: Props) {
  return (
    <div class={styles.row} data-testid={testId}>
      {cells.map((cell) => (
        <div class={styles.cell} key={cell.label} data-testid={testId ? `${testId}-cell` : undefined}>
          <span class={styles.label}>{cell.label}</span>
          <span
            class={clsx(styles.value, cell.tone === "err" && styles.valueErr, cell.tone === "warn" && styles.valueWarn)}
            data-tone={cell.tone}
          >
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
