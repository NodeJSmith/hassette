import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { getManifests } from "../api/endpoints";
import { ManifestList } from "../components/apps/manifest-list";
import { StatusFilter, type FilterValue } from "../components/apps/status-filter";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";

export function AppsPage() {
  useEffect(() => { document.title = "Apps - Hassette"; }, []);
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
    <div class="ht-apps-page">
      {error.value && <p class="ht-text-danger">{error.value}</p>}
      <div class="ht-card ht-card--apps">
        <div class="ht-apps-toolbar">
          <h2 class="ht-summary-card__title">apps</h2>
          <StatusFilter active={filter} counts={counts} />
        </div>
        <ManifestList manifests={manifests?.manifests ?? null} filter={filter} />
      </div>
    </div>
  );
}
