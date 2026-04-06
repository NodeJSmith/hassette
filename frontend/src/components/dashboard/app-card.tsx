import type { DashboardAppGridEntry } from "../../api/endpoints";
import { HealthBar } from "../shared/health-bar";
import { StatusBadge } from "../shared/status-badge";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { pluralize } from "../../utils/format";
import { errorRateToVariant } from "../../utils/status";

interface Props {
  app: DashboardAppGridEntry;
}

export function AppCard({ app }: Props) {
  const lastActivity = useRelativeTime(app.last_activity_ts);
  const total = app.total_invocations + app.total_executions;
  const errors = app.total_errors + app.total_job_errors;

  return (
    <div class="ht-app-card" data-testid={`app-card-${app.app_key}`}>
      <a href={`/apps/${app.app_key}`} class="ht-app-card__link">
        <div class="ht-app-card__header">
          <span class="ht-app-card__name">
            {app.display_name}
            {app.instance_count > 1 && (
              <span class="ht-badge ht-badge--sm ht-badge--neutral ht-ml-1">
                {pluralize(app.instance_count, "instance")}
              </span>
            )}
          </span>
          <StatusBadge status={app.status} size="small" />
        </div>
        <div class="ht-app-card__stats">
          <span class="ht-text-xs ht-text-muted">{pluralize(app.handler_count, "handler")}</span>
          <span class="ht-text-xs ht-text-muted">{pluralize(app.job_count, "job")}</span>
        </div>
        {(app.total_invocations > 0 || app.total_executions > 0) && (
          <>
            <div class="ht-app-card__counts" data-testid="app-card-counts">
              <span class="ht-text-xs ht-text-faint ht-text-mono">
                {app.total_invocations} inv &middot; {app.total_executions} exec
              </span>
            </div>
            {app.error_rate > 0 && (
              <span
                class={`ht-text-xs ht-text-${errorRateToVariant(app.error_rate_class)}`}
                data-testid="app-card-error-rate"
              >
                {app.error_rate.toFixed(1)}% errors
              </span>
            )}
          </>
        )}
        <HealthBar
          healthStatus={app.health_status}
          total={total}
          errors={errors}
        />
        <div class="ht-app-card__footer">
          <span class="ht-text-xs ht-text-muted">
            Last: {lastActivity || "—"}
          </span>
        </div>
      </a>
    </div>
  );
}
