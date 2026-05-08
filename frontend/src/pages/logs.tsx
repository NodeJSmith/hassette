import { getManifests } from "../api/endpoints";
import { LogTable } from "../components/shared/log-table";
import { useApi } from "../hooks/use-api";
import { useDocumentTitle } from "../hooks/use-document-title";

export function LogsPage() {
  useDocumentTitle("Logs");
  const manifests = useApi(getManifests);
  const appKeys = manifests.data.value?.manifests.map((m) => m.app_key).sort() ?? [];

  return (
    <div class="ht-page ht-logs-page">
      <h1 class="ht-display ht-mb-4">logs</h1>
      <div class="ht-card ht-card--logs-full">
        <LogTable showAppColumn={true} appKeys={appKeys} hideTitle />
      </div>
    </div>
  );
}
