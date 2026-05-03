import type { AppHealthData } from "../../api/endpoints";
import { formatDuration } from "../../utils/format";
import { errorRateToVariant } from "../../utils/status";
import { useRelativeTime } from "../../hooks/use-relative-time";

interface Props {
  health: AppHealthData | null;
}

function LastActivityValue({ ts }: { ts: number | null }) {
  const label = useRelativeTime(ts);
  if (!ts) return <span class="ht-health-card__value">—</span>;
  return <span class="ht-health-card__value">{label}</span>;
}

export function HealthStrip({ health }: Props) {
  if (!health) return null;

  return (
    <div class="ht-health-strip" data-testid="health-strip">
      <div class="ht-health-card">
        <span class="ht-health-card__label">Error Rate</span>
        <span class={`ht-health-card__value ht-health-card__value--${errorRateToVariant(health.error_rate_class)}`}>
          {health.error_rate.toFixed(1)}%
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Handler Avg</span>
        <span class="ht-health-card__value">
          {health.handler_avg_duration > 0 ? formatDuration(health.handler_avg_duration) : "—"}
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Job Avg</span>
        <span class="ht-health-card__value">
          {health.job_avg_duration > 0 ? formatDuration(health.job_avg_duration) : "—"}
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Last Activity</span>
        <LastActivityValue ts={health.last_activity_ts} />
      </div>
    </div>
  );
}
