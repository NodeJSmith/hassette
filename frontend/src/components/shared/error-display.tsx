import { formatDuration } from "../../utils/format";
import styles from "./detail-panel.module.css";

interface Props {
  status: string;
  durationMs: number;
  errorType?: string | null;
  errorMessage?: string | null;
}

export function ErrorDisplay({ status, durationMs, errorType, errorMessage }: Props) {
  const isTimeout = status === "timed_out";
  const isError = status === "error";
  const isCancelled = status === "cancelled";

  if (isTimeout) {
    return (
      <div className={styles.metaItem}>
        <span className={styles.label}>timeout</span>
        <span className="ht-text-mono ht-text-xs ht-text-warning">exceeded {formatDuration(durationMs)} budget</span>
      </div>
    );
  }

  if (isCancelled) {
    return (
      <div className={styles.metaItem}>
        <span className={styles.label}>result</span>
        <span className="ht-text-mono ht-text-xs ht-text-cancel">cancelled after {formatDuration(durationMs)}</span>
      </div>
    );
  }

  if (isError && errorMessage) {
    return (
      <div className={styles.metaItem}>
        <span className={styles.label}>result</span>
        <span className="ht-text-mono ht-text-xs ht-text-danger">
          {errorType ?? "Error"}: {errorMessage}
        </span>
      </div>
    );
  }

  return (
    <div className={styles.metaItem}>
      <span className={styles.label}>result</span>
      <span className="ht-text-mono ht-text-xs">completed in {formatDuration(durationMs)}</span>
    </div>
  );
}
