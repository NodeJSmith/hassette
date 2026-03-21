import type { DashboardAppGridEntry } from "../../api/endpoints";
import { HealthBar } from "../shared/health-bar";
import { formatRelativeTime } from "../../utils/format";

interface Props {
  app: DashboardAppGridEntry;
}

const VARIANT_MAP: Record<string, string> = {
  running: "running",
  failed: "failed",
  stopped: "stopped",
  disabled: "disabled",
  blocked: "disabled",
};

export function AppCard({ app }: Props) {
  const variant = VARIANT_MAP[app.status] ?? "neutral";
  const total = app.total_invocations + app.total_executions;
  const errors = app.total_errors + app.total_job_errors;

  return (
    <div class="ht-app-card" data-testid={`app-card-${app.app_key}`}>
      <a href={`/apps/${app.app_key}`} class="ht-app-card__link">
        <div class="ht-app-card__header">
          <span class="ht-app-card__name">{app.display_name}</span>
          <span class={`ht-status-badge ht-status-badge--${variant}`}>
            <span class="ht-status-badge__dot" />
            <span class="ht-status-badge__label">{app.status}</span>
          </span>
        </div>
        <div class="ht-app-card__stats">
          <span class="ht-text-xs ht-text-muted">{app.handler_count} handlers</span>
          <span class="ht-text-xs ht-text-muted">{app.job_count} jobs</span>
        </div>
        <HealthBar
          healthStatus={app.health_status}
          total={total}
          errors={errors}
        />
        {app.last_activity_ts && (
          <div class="ht-app-card__footer">
            <span class="ht-text-xs ht-text-muted">
              Last: {formatRelativeTime(app.last_activity_ts)}
            </span>
          </div>
        )}
      </a>
    </div>
  );
}
