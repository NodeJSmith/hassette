import type { ListenerData, JobData } from "../../api/endpoints";
import { computeHandlerStats } from "../../utils/handler-stats";
import { useMediaQuery, BREAKPOINT_SMALL_MOBILE } from "../../hooks/use-media-query";

interface HandlersHealthStripProps {
  listeners: ListenerData[];
  jobs: JobData[];
  timeLabel?: string;
}

export function HandlersHealthStrip({ listeners, jobs, timeLabel }: HandlersHealthStripProps) {
  const handlerCount = listeners.length;
  const jobCount = jobs.length;
  const isSmallMobile = useMediaQuery(BREAKPOINT_SMALL_MOBILE);

  const { totalInvocations, totalExecutions, totalFailed, totalTimedOut } =
    computeHandlerStats(listeners, jobs);

  const totalAll = totalInvocations + totalExecutions;
  const totalErrors = totalFailed + totalTimedOut;
  const successRate = totalAll > 0
    ? Math.round(((totalAll - totalErrors) / totalAll) * 100)
    : 100;

  const hasErrors = totalErrors > 0;
  const cols = isSmallMobile ? 4 : 5;

  return (
    <div class="ht-stats-strip" style={`--stats-cols: ${cols}`} data-testid="handlers-health-strip">
      <div class="ht-stats-strip__cell">
        <span class="ht-stats-strip__label">Handlers</span>
        <span class="ht-stats-strip__value">{handlerCount + jobCount}</span>
      </div>

      <div class="ht-stats-strip__cell">
        <span class="ht-stats-strip__label">Invocations{timeLabel ? ` · ${timeLabel}` : ""}</span>
        <span class="ht-stats-strip__value">{totalAll}</span>
      </div>

      <div class="ht-stats-strip__cell">
        <span class="ht-stats-strip__label">Success Rate</span>
        <span class={`ht-stats-strip__value${hasErrors ? " ht-stats-strip__value--warn" : ""}`}>
          {totalAll > 0 ? `${successRate}%` : "—"}
        </span>
      </div>

      {isSmallMobile ? (
        <div class="ht-stats-strip__cell">
          <span class="ht-stats-strip__label">Errors</span>
          <span class={`ht-stats-strip__value${totalErrors > 0 ? " ht-stats-strip__value--err" : ""}`}>
            {totalErrors > 0 ? totalErrors : "—"}
          </span>
        </div>
      ) : (
        <>
          <div class="ht-stats-strip__cell">
            <span class="ht-stats-strip__label">Failed</span>
            <span class={`ht-stats-strip__value${totalFailed > 0 ? " ht-stats-strip__value--err" : ""}`}>
              {totalFailed > 0 ? totalFailed : "—"}
            </span>
          </div>

          <div class="ht-stats-strip__cell">
            <span class="ht-stats-strip__label">Timed Out</span>
            <span class={`ht-stats-strip__value${totalTimedOut > 0 ? " ht-stats-strip__value--warn" : ""}`}>
              {totalTimedOut > 0 ? totalTimedOut : "—"}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
