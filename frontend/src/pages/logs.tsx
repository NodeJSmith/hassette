import { useEffect } from "preact/hooks";
import { getManifests } from "../api/endpoints";
import { IconScroll } from "../components/shared/icons";
import { LogTable } from "../components/shared/log-table";
import { useApi } from "../hooks/use-api";

export function LogsPage() {
  useEffect(() => { document.title = "Logs - Hassette"; }, []);
  const manifests = useApi(getManifests);
  const appKeys = manifests.data.value?.manifests.map((m) => m.app_key).sort() ?? [];

  return (
    <div>
      <h1 class="ht-heading-4 ht-mb-4">
        <IconScroll />
        <span>Log Viewer</span>
      </h1>
      <div class="ht-card">
        <LogTable showAppColumn={true} appKeys={appKeys} />
      </div>
    </div>
  );
}
