import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getManifests } from "../api/endpoints";
import { ManifestList } from "../components/apps/manifest-list";
import { StatusFilter, type FilterValue } from "../components/apps/status-filter";
import { IconGrid } from "../components/shared/icons";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";

export function AppsPage() {
  const filter = useRef(signal<FilterValue>("all")).current;
  const { data, loading, error } = useApi(getManifests);

  const manifests = data.value;
  const counts: Record<string, number> = {};
  if (manifests) {
    for (const m of manifests.manifests) {
      counts[m.status] = (counts[m.status] ?? 0) + 1;
    }
  }

  if (loading.value) return <Spinner />;

  return (
    <div>
      <h1 class="ht-heading-4 ht-mb-4">
        <IconGrid />
        <span>App Management</span>
      </h1>
      {error.value && <p class="ht-text-danger">{error.value}</p>}
      <div class="ht-card">
        <StatusFilter active={filter} counts={counts} />
        <ManifestList manifests={manifests?.manifests ?? null} filter={filter} />
      </div>
    </div>
  );
}
