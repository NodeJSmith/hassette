import { LogTable } from "./log-table";
import styles from "./execution-logs.module.css";

interface Props {
  executionId: string;
}

export function ExecutionLogs({ executionId }: Props) {
  const viewAllHref = `/logs?execution_id=${encodeURIComponent(executionId)}`;

  return (
    <div class={styles.section} data-testid="execution-logs-section">
      <span class={styles.label}>logs</span>
      <LogTable
        context="execution"
        executionId={executionId}
        useLocalState
        emptyTitle="no logs for this execution"
        emptyBody="this execution did not produce any log output, or logs have been removed by the retention policy."
      />
      <p class={styles.viewAll}>
        <a href={viewAllHref} data-testid="view-all-logs-link">View all logs</a>
      </p>
    </div>
  );
}
