import type { DashboardKpis } from "../../api/endpoints";
import { pluralize } from "../../utils/format";
import { errorRateToVariant } from "../../utils/status";

/** Drives CSS prominence rules in global.css (.ht-kpi-strip > [data-kpi]) */
const KPI_ERROR_RATE = "error-rate";

interface Props {
  data: DashboardKpis | null;
  appCount?: number;
  runningCount?: number;
}

export function KpiStrip({ data, appCount = 0, runningCount = 0 }: Props) {
  if (!data) return null;

  const uptimeH = data.uptime_seconds ? Math.floor(data.uptime_seconds / 3600) : 0;
  const uptimeM = data.uptime_seconds ? Math.floor((data.uptime_seconds % 3600) / 60) : 0;

  return (
    <div class="ht-kpi-strip" data-testid="kpi-strip">
      <div class="ht-health-card" data-kpi={KPI_ERROR_RATE}>
        <span class="ht-health-card__label">Error Rate</span>
        <span class={`ht-health-card__value ht-health-card__value--${errorRateToVariant(data.error_rate_class)}`}>
          {data.error_rate.toFixed(1)}%
        </span>
        <span class="ht-health-card__detail">
          {data.total_invocations + data.total_executions > 0
            ? `${data.total_errors + data.total_job_errors} / ${pluralize(data.total_invocations + data.total_executions, "invocation")}`
            : "No data"}
        </span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Apps</span>
        <span class="ht-health-card__value">{appCount}</span>
        <span class="ht-health-card__detail">{runningCount} running</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Handlers</span>
        <span class="ht-health-card__value">{data.total_handlers}</span>
        <span class="ht-health-card__detail">{pluralize(data.total_invocations, "invocation")}</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Jobs</span>
        <span class="ht-health-card__value">{data.total_jobs}</span>
        <span class="ht-health-card__detail">{pluralize(data.total_executions, "execution")}</span>
      </div>
      <div class="ht-health-card">
        <span class="ht-health-card__label">Uptime</span>
        <span class="ht-health-card__value">
          {data.uptime_seconds ? `${uptimeH}h ${uptimeM}m` : "—"}
        </span>
        {data.uptime_seconds ? (
          <span class="ht-health-card__detail">
            Started {new Date(Date.now() - data.uptime_seconds * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
          </span>
        ) : null}
      </div>
    </div>
  );
}
