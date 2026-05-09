import type { ListenerData, JobData } from "../../api/endpoints";
import { computeHandlerStats } from "../../utils/handler-stats";
import { useMediaQuery, BREAKPOINT_SMALL_MOBILE } from "../../hooks/use-media-query";
import { StatsStrip, type StatsStripCell } from "../shared/stats-strip";

interface HandlersHealthStripProps {
  listeners: ListenerData[];
  jobs: JobData[];
  timeLabel?: string;
}

export function HandlersHealthStrip({ listeners, jobs, timeLabel }: HandlersHealthStripProps) {
  const isSmallMobile = useMediaQuery(BREAKPOINT_SMALL_MOBILE);

  const { totalInvocations, totalExecutions, totalFailed, totalTimedOut } =
    computeHandlerStats(listeners, jobs);

  const totalAll = totalInvocations + totalExecutions;
  const totalErrors = totalFailed + totalTimedOut;
  const successRate = totalAll > 0
    ? Math.round(((totalAll - totalErrors) / totalAll) * 100)
    : 100;

  const cells: StatsStripCell[] = [
    { label: "Handlers", value: listeners.length + jobs.length },
    { label: `Invocations${timeLabel ? ` · ${timeLabel}` : ""}`, value: totalAll },
    { label: "Success Rate", value: totalAll > 0 ? `${successRate}%` : "—", tone: totalErrors > 0 ? "warn" : undefined },
  ];

  if (isSmallMobile) {
    cells.push({ label: "Errors", value: totalErrors > 0 ? totalErrors : "—", tone: totalErrors > 0 ? "err" : undefined });
  } else {
    cells.push({ label: "Failed", value: totalFailed > 0 ? totalFailed : "—", tone: totalFailed > 0 ? "err" : undefined });
    cells.push({ label: "Timed Out", value: totalTimedOut > 0 ? totalTimedOut : "—", tone: totalTimedOut > 0 ? "warn" : undefined });
  }

  return <StatsStrip cells={cells} cols={isSmallMobile ? 4 : 5} data-testid="handlers-health-strip" />;
}
