import { healthGradeToVariant } from "../../utils/status";

interface Props {
  healthStatus: string;
  total: number;
  errors: number;
}

export function HealthBar({ healthStatus, total, errors }: Props) {
  const successRate = total > 0 ? ((total - errors) / total) * 100 : 100;

  return (
    <div class="ht-health-bar">
      <div
        class={`ht-health-bar__fill ht-health-bar__fill--${healthGradeToVariant(healthStatus)}`}
        style={{ width: `${successRate}%` }}
      />
    </div>
  );
}
