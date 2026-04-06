import type { DashboardAppGridEntry } from "../../api/endpoints";
import { INACTIVE_STATUSES } from "../../utils/status";
import { AppCard } from "./app-card";

function byName(a: DashboardAppGridEntry, b: DashboardAppGridEntry): number {
  return a.display_name.localeCompare(b.display_name);
}

interface Props {
  apps: DashboardAppGridEntry[] | null;
}

export function AppGrid({ apps }: Props) {
  if (!apps) return null;
  if (apps.length === 0) {
    return <p class="ht-text-secondary">No apps registered.</p>;
  }

  const active = apps.filter((a) => !INACTIVE_STATUSES.has(a.status)).sort(byName);
  const inactive = apps.filter((a) => INACTIVE_STATUSES.has(a.status)).sort(byName);

  return (
    <div id="dashboard-app-grid">
      {active.length > 0 && (
        <div class="ht-app-grid">
          {active.map((app) => (
            <AppCard key={app.app_key} app={app} />
          ))}
        </div>
      )}
      {inactive.length > 0 && (
        <>
          <h3 class="ht-app-grid__section-label">Inactive</h3>
          <div class="ht-app-grid ht-app-grid--inactive">
            {inactive.map((app) => (
              <AppCard key={app.app_key} app={app} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
