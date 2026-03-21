import { getManifests } from "../api/endpoints";
import { LogTable } from "../components/shared/log-table";
import { useApi } from "../hooks/use-api";

export function LogsPage() {
  const manifests = useApi(getManifests);
  const appKeys = manifests.data.value?.manifests.map((m) => m.app_key).sort() ?? [];

  return (
    <div>
      <h1 class="ht-heading-4 ht-mb-4">
        <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15 12h-5" /><path d="M15 8h-5" /><path d="M19 17V5a2 2 0 0 0-2-2H4" />
          <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2" />
        </svg>
        <span>Log Viewer</span>
      </h1>
      <div class="ht-card">
        <LogTable showAppColumn={true} appKeys={appKeys} />
      </div>
    </div>
  );
}
