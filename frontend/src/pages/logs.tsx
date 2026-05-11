import { LogTable } from "../components/shared/log-table";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useAppState } from "../state/context";

export function LogsPage() {
  useDocumentTitle("Logs");
  const { manifests } = useAppState();
  const appKeys = manifests.value.map((m) => m.app_key).sort();

  return (
    <div class="ht-page ht-logs-page">
      <div class="ht-page-header">
        <h1 class="ht-display">logs</h1>
      </div>
      <div class="ht-card ht-card--compact ht-card--logs-full">
        <LogTable showAppColumn={true} appKeys={appKeys} hideTitle />
      </div>
    </div>
  );
}
