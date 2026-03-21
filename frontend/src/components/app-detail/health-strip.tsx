import type { AppHealthData } from "../../api/endpoints";
import { formatDuration, formatRelativeTime } from "../../utils/format";

interface Props {
  health: AppHealthData | null;
  status: string;
}

export function HealthStrip({ health, status }: Props) {
  if (!health) return null;

  const cards = [
    { label: "Status", value: status, statusClass: `ht-status-${status}` },
    {
      label: "Error Rate",
      value: `${health.error_rate.toFixed(1)}%`,
      statusClass: `ht-health-${health.error_rate_class}`,
    },
    { label: "Avg Duration", value: formatDuration(health.handler_avg_duration) },
    {
      label: "Last Activity",
      value: health.last_activity_ts ? formatRelativeTime(health.last_activity_ts) : "—",
    },
  ];

  return (
    <div class="ht-kpi-strip">
      {cards.map((card) => (
        <div key={card.label} class={`ht-health-card${card.statusClass ? ` ${card.statusClass}` : ""}`}>
          <div class="ht-health-card-label">{card.label}</div>
          <div class="ht-health-card-value">{card.value}</div>
        </div>
      ))}
    </div>
  );
}
