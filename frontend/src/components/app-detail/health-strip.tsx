import type { AppHealthData } from "../../api/endpoints";
import { formatDuration, formatRelativeTime } from "../../utils/format";

interface Props {
  health: AppHealthData | null;
  status: string;
}

export function HealthStrip({ health, status }: Props) {
  if (!health) return null;

  return (
    <div class="ht-kpi-strip">
      <div class="ht-health-card">
        <span class="ht-health-card__label">Status</span>
        <span class={`ht-health-card__value ht-status-text--${status}`}>{status}</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Error Rate</span>
        <span class={`ht-health-card__value ${health.error_rate_class}`}>
          {health.error_rate.toFixed(1)}%
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Avg Duration</span>
        <span class="ht-health-card__value">{formatDuration(health.handler_avg_duration)}</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Last Activity</span>
        <span class="ht-health-card__value">
          {health.last_activity_ts ? formatRelativeTime(health.last_activity_ts) : "—"}
        </span>
      </div>
    </div>
  );
}
