import { LogTable } from "../components/shared/log-table";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";
import { useQueryParams } from "../hooks/use-query-params";
import { Card } from "../components/shared/card";
import styles from "./logs.module.css";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { manifests } = useAppState();
  const appKeys = manifests.value.map((m) => m.app_key).sort();
  const qp = useQueryParams();
  const executionId = qp.get("execution_id");

  return (
    <div class={`ht-page ${styles.page}`} data-testid="logs-page">
      <div class="ht-page-header">
        <h1 class="ht-display">logs</h1>
      </div>
      <Card variant="compact" class={styles.cardFull} data-testid="logs-card">
        <LogTable
          context="global"
          appKeys={appKeys}
          executionId={executionId}
        />
      </Card>
    </div>
  );
}
