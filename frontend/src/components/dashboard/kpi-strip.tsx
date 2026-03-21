import type { DashboardKpis } from "../../api/endpoints";
import { formatDuration } from "../../utils/format";

interface Props {
  data: DashboardKpis | null;
}

export function KpiStrip({ data }: Props) {
  if (!data) return null;

  return (
    <div class="ht-kpi-strip" data-testid="kpi-strip">
      <div class="ht-health-card">
        <span class="ht-health-card__label">Handlers</span>
        <span class="ht-health-card__value">{data.total_handlers}</span>
        <span class="ht-health-card__detail">{data.total_invocations} invocations</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Jobs</span>
        <span class="ht-health-card__value">{data.total_jobs}</span>
        <span class="ht-health-card__detail">{data.total_executions} executions</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Error Rate</span>
        <span class={`ht-health-card__value ${data.error_rate_class}`}>
          {data.error_rate.toFixed(1)}%
        </span>
        <span class="ht-health-card__detail">
          {data.total_errors + data.total_job_errors} errors
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Avg Duration</span>
        <span class="ht-health-card__value">{formatDuration(data.avg_handler_duration_ms)}</span>
        <span class="ht-health-card__detail">
          jobs: {formatDuration(data.avg_job_duration_ms)}
        </span>
      </div>
    </div>
  );
}
