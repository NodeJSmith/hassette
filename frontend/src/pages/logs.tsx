import { useSignal } from "../hooks/use-signal";
import { useSubscribe } from "../hooks/use-subscribe";
import { LogTable } from "../components/shared/log-table";
import { TableCard } from "../components/shared/table-card";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";
import { useQueryParams } from "../hooks/use-query-params";
import styles from "./logs.module.css";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { manifests } = useAppState();
  const appKeys = manifests.value.map((m) => m.app_key).sort();
  const qp = useQueryParams();
  const executionId = qp.get("execution_id");

  // Search state owned by LogsPage — passed to both TableCard (search slot) and LogTable
  const search = useSignal("");
  useSubscribe(search);

  const searchInput = (
    <input
      type="text"
      class="ht-search"
      placeholder="Search logs…"
      aria-label="Search logs"
      value={search.value}
      onInput={(e) => { search.value = (e.target as HTMLInputElement).value; }}
      data-testid="logs-search"
    />
  );

  return (
    <div class={`ht-page ${styles.page}`} data-testid="logs-page">
      <div class="ht-page-header">
        <h1 class="ht-display">logs</h1>
      </div>
      <TableCard search={searchInput} class={styles.cardFull} data-testid="logs-card">
        <LogTable
          context="global"
          appKeys={appKeys}
          executionId={executionId}
          search={search.value}
        />
      </TableCard>
    </div>
  );
}
