interface Props {
  /** Server-computed classification: "excellent" | "good" | "warning" | "critical" | "unknown" */
  healthStatus: string;
  /** Total invocations + executions */
  total: number;
  /** Total errors */
  errors: number;
}

export function HealthBar({ healthStatus, total, errors }: Props) {
  const successRate = total > 0 ? ((total - errors) / total) * 100 : 100;

  return (
    <div class={`ht-health-bar ht-health-${healthStatus}`}>
      <div class="ht-health-bar-fill" style={{ width: `${successRate}%` }} />
    </div>
  );
}
