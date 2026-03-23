import type { AppHealthData } from "../../api/endpoints";
import { formatDuration } from "../../utils/format";

interface Props {
  health: AppHealthData | null;
  status: string;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const STATUS_COLOR_MAP: Record<string, string> = {
  running: "good",
  failed: "bad",
  stopped: "warn",
  blocked: "warn",
};

export function HealthStrip({ health, status }: Props) {
  if (!health) return null;

  return (
    <div class="ht-kpi-strip" data-testid="health-strip">
      <div class="ht-health-card">
        <span class="ht-health-card__label">Status</span>
        <span class={`ht-health-card__value ${STATUS_COLOR_MAP[status] ?? ""}`}>{capitalize(status)}</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Error Rate</span>
        <span class={`ht-health-card__value ${health.error_rate_class}`}>
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
    </div>
  );
}
