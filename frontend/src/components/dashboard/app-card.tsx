import type { DashboardAppGridEntry } from "../../api/endpoints";
import { HealthBar } from "../shared/health-bar";
import { StatusBadge } from "../shared/status-badge";
import { formatRelativeTime } from "../../utils/format";

interface Props {
  app: DashboardAppGridEntry;
}

export function AppCard({ app }: Props) {
  return (
    <a href={`/apps/${app.app_key}`} class="ht-app-card">
      <div class="ht-app-card-header">
        <span class="ht-app-card-name">{app.display_name}</span>
        <StatusBadge status={app.status} size="small" />
      </div>
      <HealthBar
        healthStatus={app.health_status}
        total={app.total_invocations + app.total_executions}
        errors={app.total_errors}
      />
      <div class="ht-app-card-meta">
        <span>{app.handler_count} handlers</span>
        <span>{app.job_count} jobs</span>
        {app.last_activity_ts && (
          <span class="ht-text-secondary">{formatRelativeTime(app.last_activity_ts)}</span>
        )}
      </div>
    </a>
  );
}
