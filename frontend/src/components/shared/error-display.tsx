import clsx from "clsx";

import { formatDuration } from "../../utils/format";
import styles from "./detail-panel.module.css";

interface Props {
  status: string;
  durationMs: number;
  errorType?: string | null;
  errorMessage?: string | null;
}

interface ResultDisplay {
  label: string;
  toneClass?: string;
  message: string;
}

function resolveResultDisplay(
  status: string,
  durationMs: number,
  errorType?: string | null,
  errorMessage?: string | null,
): ResultDisplay {
  if (status === "timed_out") {
    return { label: "timeout", toneClass: "ht-text-warning", message: `exceeded ${formatDuration(durationMs)} budget` };
  }

  if (status === "cancelled") {
    return { label: "result", toneClass: "ht-text-cancel", message: `cancelled after ${formatDuration(durationMs)}` };
  }

  if (status === "error" && errorMessage) {
    return { label: "result", toneClass: "ht-text-danger", message: `${errorType ?? "Error"}: ${errorMessage}` };
  }

  return { label: "result", message: `completed in ${formatDuration(durationMs)}` };
}

export function ErrorDisplay({ status, durationMs, errorType, errorMessage }: Props) {
  const { label, toneClass, message } = resolveResultDisplay(status, durationMs, errorType, errorMessage);

  return (
    <div className={styles.metaItem}>
      <span className={styles.label}>{label}</span>
      <span className={clsx("ht-text-mono ht-text-xs", toneClass)}>{message}</span>
    </div>
  );
}
