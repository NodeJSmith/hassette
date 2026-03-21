import type { DashboardAppGridEntry } from "../../api/endpoints";
import { AppCard } from "./app-card";

interface Props {
  apps: DashboardAppGridEntry[] | null;
}

export function AppGrid({ apps }: Props) {
  if (!apps) return null;
  if (apps.length === 0) {
    return <p class="ht-text-secondary">No apps registered.</p>;
  }

  return (
    <div class="ht-app-grid">
      {apps.map((app) => (
        <AppCard key={app.app_key} app={app} />
      ))}
    </div>
  );
}
