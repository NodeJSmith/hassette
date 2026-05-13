import { LogTable } from "../components/shared/log-table";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";
import { useQueryParams } from "../hooks/use-query-params";
import { getLogsByExecution } from "../api/endpoints";
import { Card } from "../components/shared/card";
import styles from "./logs.module.css";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { manifests } = useAppState();
  const appKeys = manifests.value.map((m) => m.app_key).sort();
  const qp = useQueryParams();
  const executionId = qp.get("execution_id");

  if (executionId) {
    const fetcher = () =>
      getLogsByExecution(executionId).then((r) => r.records);

    return (
      <div class={`ht-page ${styles.page}`} data-testid="logs-page">
        <div class="ht-page-header">
          <h1 class="ht-display">logs</h1>
        </div>
        <div class={styles.executionBanner} data-testid="execution-filter-banner">
          Viewing logs for execution{" "}
          <span class="ht-text-mono">{executionId}</span>
          {" — "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              qp.set({ execution_id: null });
            }}
          >
            Clear filter
          </a>
        </div>
        <Card variant="compact" class={styles.cardFull} data-testid="logs-card">
          <LogTable
            showAppColumn={true}
            appKeys={appKeys}
            hideTitle
            mode="historical"
            fetcher={fetcher}
            hideExecutionId={true}
          />
        </Card>
      </div>
    );
  }

  return (
    <div class={`ht-page ${styles.page}`} data-testid="logs-page">
      <div class="ht-page-header">
        <h1 class="ht-display">logs</h1>
      </div>
      <Card variant="compact" class={styles.cardFull} data-testid="logs-card">
        <LogTable showAppColumn={true} appKeys={appKeys} hideTitle hideExecutionId={false} />
      </Card>
    </div>
  );
}
