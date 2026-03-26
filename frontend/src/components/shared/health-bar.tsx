import { healthGradeToVariant } from "../../utils/status";

interface Props {
  healthStatus: string;
  total: number;
  errors: number;
}

export function HealthBar({ healthStatus, total, errors }: Props) {
  const successRate = total > 0 ? ((total - errors) / total) * 100 : 100;

  if (total === 0) {
    return (
      <div class="ht-health-bar" aria-hidden="true">
        <div
          class="ht-health-bar__fill ht-health-bar__fill--neutral"
          style={{ width: "100%" }}
        />
      </div>
    );
  }

  return (
    <div
      class="ht-health-bar"
      role="progressbar"
      aria-valuenow={Math.round(successRate)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Health: ${Math.round(successRate)}% success rate`}
    >
      <div
        class={`ht-health-bar__fill ht-health-bar__fill--${healthGradeToVariant(healthStatus)}`}
        style={{ width: `${successRate}%` }}
      />
    </div>
  );
}
