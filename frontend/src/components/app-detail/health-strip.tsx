import type { JobData, ListenerData } from "../../api/endpoints";
import { BREAKPOINT_SMALL_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { computeHandlerStats } from "../../utils/handler-stats";
import { StatsStrip, type StatsStripCell } from "../shared/stats-strip";

interface HandlersHealthStripProps {
  listeners: ListenerData[];
  jobs: JobData[];
}

export function HandlersHealthStrip({ listeners, jobs }: HandlersHealthStripProps) {
  const isSmallMobile = useMediaQuery(BREAKPOINT_SMALL_MOBILE);

  const { totalInvocations, totalExecutions, totalFailed, totalTimedOut, totalCancelled } = computeHandlerStats(
    listeners,
    jobs,
  );

  const totalAll = totalInvocations + totalExecutions;
  // Cancelled is deliberately excluded from the error count: cancellation is the designed
  // outcome of restart/replace overlap modes, not a failure. It gets its own column below.
  // Matches the backend success_rate, which counts only error + timed_out as failures.
  const totalErrors = totalFailed + totalTimedOut;
  const successRate = totalAll > 0 ? Math.round(((totalAll - totalErrors) / totalAll) * 100) : 100;

  const cells: StatsStripCell[] = [
    { label: "Handlers", value: listeners.length + jobs.length },
    { label: isSmallMobile ? "Calls" : "Invocations", value: totalAll },
    {
      label: "Success Rate",
      value: totalAll > 0 ? `${successRate}%` : "0%",
      tone: totalErrors > 0 ? "warn" : undefined,
    },
  ];

  if (isSmallMobile) {
    // Small mobile collapses Failed + Timed Out into one "Errors" cell to save width.
    // Cancelled is omitted here (not an error, and space is tight) — it stays visible
    // on the per-handler detail panel.
    cells.push({
      label: "Errors",
      value: totalErrors,
      tone: totalErrors > 0 ? "err" : undefined,
    });
  } else {
    cells.push({
      label: "Failed",
      value: totalFailed,
      tone: totalFailed > 0 ? "err" : undefined,
    });
    cells.push({
      label: "Timed Out",
      value: totalTimedOut,
      tone: totalTimedOut > 0 ? "warn" : undefined,
    });
    cells.push({
      label: "Cancelled",
      value: totalCancelled,
      tone: totalCancelled > 0 ? "cancel" : undefined,
    });
  }

  return <StatsStrip cells={cells} cols={isSmallMobile ? 4 : 6} data-testid="handlers-health-strip" />;
}
