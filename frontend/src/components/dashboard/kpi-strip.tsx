import type { DashboardKpis } from "../../api/endpoints";
import { formatDuration } from "../../utils/format";

interface Props {
  data: DashboardKpis | null;
}

export function KpiStrip({ data }: Props) {
  if (!data) return null;

  const cards = [
    {
      label: "Handlers",
      value: String(data.total_handlers),
      detail: `${data.total_invocations} invocations`,
    },
    {
      label: "Jobs",
      value: String(data.total_jobs),
      detail: `${data.total_executions} executions`,
    },
    {
      label: "Error Rate",
      value: `${data.error_rate.toFixed(1)}%`,
      detail: `${data.total_errors + data.total_job_errors} errors`,
      statusClass: data.error_rate_class,
    },
    {
      label: "Avg Duration",
      value: formatDuration(data.avg_handler_duration_ms),
      detail: `jobs: ${formatDuration(data.avg_job_duration_ms)}`,
    },
  ];

  return (
    <div class="ht-kpi-strip">
      {cards.map((card) => (
        <div key={card.label} class={`ht-health-card${card.statusClass ? ` ht-health-${card.statusClass}` : ""}`}>
          <div class="ht-health-card-label">{card.label}</div>
          <div class="ht-health-card-value">{card.value}</div>
          <div class="ht-health-card-detail">{card.detail}</div>
        </div>
      ))}
    </div>
  );
}
