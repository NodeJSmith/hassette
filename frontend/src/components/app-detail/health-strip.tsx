import type { ListenerData, JobData } from "../../api/endpoints";
import { computeHandlerStats } from "../../utils/handler-stats";

interface HandlersHealthStripProps {
  listeners: ListenerData[];
  jobs: JobData[];
}

export function HandlersHealthStrip({ listeners, jobs }: HandlersHealthStripProps) {
  const handlerCount = listeners.length;
  const jobCount = jobs.length;

  const { totalInvocations, totalExecutions, totalFailed, totalTimedOut } =
    computeHandlerStats(listeners, jobs);

  const totalAll = totalInvocations + totalExecutions;
  const totalErrors = totalFailed + totalTimedOut;
  const successRate = totalAll > 0
    ? Math.round(((totalAll - totalErrors) / totalAll) * 100)
    : 100;

  const hasErrors = totalErrors > 0;

  return (
    <div class="ht-health-strip" data-testid="handlers-health-strip">
      {/* Column 1: HANDLERS */}
      <div class="ht-health-card">
        <span class="ht-health-card__label">Handlers</span>
        <span class="ht-health-card__value">{handlerCount + jobCount}</span>
      </div>

      {/* Column 2: INVOCATIONS · 1H */}
      <div class="ht-health-card">
        <span class="ht-health-card__label">Invocations · 1H</span>
        <span class="ht-health-card__value">{totalAll}</span>
      </div>

      {/* Column 3: SUCCESS RATE */}
      <div class="ht-health-card">
        <span class="ht-health-card__label">Success Rate</span>
        <span class={`ht-health-card__value${hasErrors ? " ht-health-card__value--warning" : ""}`}>
          {successRate}%
        </span>
      </div>

      {/* Column 4: FAILED */}
      <div class="ht-health-card">
        <span class="ht-health-card__label">Failed</span>
        <span class={`ht-health-card__value${totalFailed > 0 ? " ht-health-card__value--danger" : ""}`}>
          {totalFailed > 0 ? totalFailed : "—"}
        </span>
      </div>

      {/* Column 5: TIMED OUT */}
      <div class="ht-health-card">
        <span class="ht-health-card__label">Timed Out</span>
        <span class={`ht-health-card__value${totalTimedOut > 0 ? " ht-health-card__value--warning" : ""}`}>
          {totalTimedOut > 0 ? totalTimedOut : "—"}
        </span>
      </div>
    </div>
  );
}
