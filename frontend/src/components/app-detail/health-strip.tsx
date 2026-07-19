import type { JobData, ListenerData } from "../../api/endpoints";
import { BREAKPOINT_SMALL_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { formatDurationOrDash } from "../../utils/format";
import { computeHandlerStats } from "../../utils/handler-stats";
import { StatsStrip, type StatsStripCell } from "../shared/stats-strip";

interface OverviewHealthStripProps {
  listeners: ListenerData[];
  jobs: JobData[];
}

export function OverviewHealthStrip({ listeners, jobs }: OverviewHealthStripProps) {
  const isSmallMobile = useMediaQuery(BREAKPOINT_SMALL_MOBILE);

  const { totalInvocations, totalExecutions, totalFailed, totalTimedOut, totalAvgDurationMs } = computeHandlerStats(
    listeners,
    jobs,
  );

  const totalRuns = totalInvocations + totalExecutions;
  // Cancelled is deliberately excluded from the error rate: cancellation is the designed
  // outcome of restart/replace overlap modes, not a failure. Timed-out still contributes,
  // matching the backend success_rate, which counts only error + timed_out as failures.
  const totalErrors = totalFailed + totalTimedOut;
  const errorRate = totalRuns > 0 ? Math.round((totalErrors / totalRuns) * 100) : 0;

  const cells: StatsStripCell[] = [
    { label: "Handlers", value: listeners.length + jobs.length },
    { label: isSmallMobile ? "Runs" : "Total Runs", value: totalRuns },
    {
      label: "Failed",
      value: totalFailed,
      tone: totalFailed > 0 ? "err" : undefined,
    },
    {
      label: "Error Rate",
      value: totalRuns > 0 ? `${errorRate}%` : "0%",
      tone: totalErrors > 0 ? "err" : undefined,
    },
  ];

  if (!isSmallMobile) {
    cells.push({
      label: "Avg Duration",
      value: formatDurationOrDash(totalAvgDurationMs),
    });
  }

  return <StatsStrip cells={cells} cols={cells.length} data-testid="overview-health-strip" />;
}
