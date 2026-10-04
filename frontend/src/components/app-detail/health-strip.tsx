import { getAppHealth } from "../../api/endpoints";
import { BREAKPOINT_SMALL_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { isExecutionDefined, useAppExecution } from "../../hooks/use-scoped-execution";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { formatOptionalDuration } from "../../utils/format";
import { StatsStrip, type StatsStripCell } from "../shared/stats-strip";

interface OverviewHealthStripProps {
  appKey: string;
  resolvedInstanceIndex: number;
  /** Registered handlers and jobs. Health itself comes from the server and also counts runs of
   *  handlers and jobs removed since, so the two are not derived from the same rows. */
  handlerCount: number;
}

export function OverviewHealthStrip({ appKey, resolvedInstanceIndex, handlerCount }: OverviewHealthStripProps) {
  const isSmallMobile = useMediaQuery(BREAKPOINT_SMALL_MOBILE);
  const { data: health, isError } = useScopedQuery(
    queryKeys.appHealth.base(appKey, resolvedInstanceIndex),
    (since, signal) => getAppHealth(appKey, resolvedInstanceIndex, since, signal),
  );

  const execution = useAppExecution(appKey);
  useQueryInvalidator(execution, isExecutionDefined, queryKeys.appHealth.prefix(appKey));

  const errorRate = health?.error_rate ?? null;
  const showErrorTone = isError || (errorRate ?? 0) > 0;
  const cells: StatsStripCell[] = [
    { label: "Handlers", value: handlerCount },
    {
      label: "Error Rate",
      value: formatErrorRate(isError, errorRate),
      tone: showErrorTone ? "err" : undefined,
    },
    { label: "Handler Avg", value: formatOptionalDuration(health?.handler_avg_duration_ms) },
  ];

  if (!isSmallMobile) {
    cells.push({ label: "Job Avg", value: formatOptionalDuration(health?.job_avg_duration_ms) });
  }

  return <StatsStrip cells={cells} cols={cells.length} data-testid="overview-health-strip" />;
}

function formatErrorRate(isError: boolean, errorRate: number | null): string {
  // A failed request reads "unavailable", so a telemetry outage never passes for an idle app.
  if (isError) return "unavailable";
  if (errorRate === null) return "—";
  const rounded = Math.round(errorRate);
  // Any failure stays visible: a rate that rounds to zero reads "<1%", never "0%".
  if (errorRate > 0 && rounded === 0) return "<1%";
  return `${rounded}%`;
}
