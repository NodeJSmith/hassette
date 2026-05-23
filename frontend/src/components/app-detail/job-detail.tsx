import type { JobData } from "../../api/endpoints";
import { getJobExecutions } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppState } from "../../state/context";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { formatDurationOrDash, formatOptionalDuration, formatTriggerDetail } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { Chip } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import chipStyles from "./handler-chips.module.css";
import { HandlerDetailLayout } from "./handler-detail-layout";
import layoutStyles from "./handler-detail-layout.module.css";
import { jobHealthKind } from "./handler-list";

function ScheduleChips({ job }: { job: JobData }) {
  const chips: Array<{ label: string }> = [];
  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  if (chips.length === 0) return null;
  return (
    <div class={chipStyles.chipRow} data-testid="schedule-chips">
      {chips.map((chip) => (
        <Chip key={chip.label} variant="schedule">
          {chip.label}
        </Chip>
      ))}
    </div>
  );
}

function buildJobStatsCells(job: JobData, lastExecutedLabel: string): DetailStatsCell[] {
  return [
    { label: "Runs", value: job.total_executions },
    { label: "Successful", value: job.successful },
    { label: "Last", value: job.last_executed_at ? lastExecutedLabel || "—" : "—" },
    { label: "Failed", value: job.failed > 0 ? job.failed : "—", tone: job.failed > 0 ? "err" : undefined },
    {
      label: "Timed Out",
      value: job.timed_out > 0 ? job.timed_out : "—",
      tone: job.timed_out > 0 ? "warn" : undefined,
    },
    { label: "Min", value: formatOptionalDuration(job.min_duration_ms) },
    { label: "Avg", value: formatDurationOrDash(job.avg_duration_ms) },
    { label: "Max", value: formatOptionalDuration(job.max_duration_ms) },
  ];
}

interface Props {
  job: JobData;
  onSwitchToCode?: (line?: number) => void;
}

export function JobDetail({ job, onSwitchToCode }: Props) {
  const { data: executions, isPending: loading } = useScopedQuery(
    queryKeys.jobExecutions(job.job_id),
    (since, signal) => getJobExecutions(job.job_id, DETAIL_FETCH_LIMIT, since, signal),
  );

  const { executionCompleted } = useAppState();
  const lastExecutedLabel = useRelativeTime(job.last_executed_at);
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const fireAtLabel = useRelativeTime(job.fire_at ?? null);

  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.job_id === job.job_id) ?? false,
    queryKeys.jobExecutions(job.job_id),
  );

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);
  const jobKind = jobHealthKind(job);

  let nextRunText: string | null = null;
  if (job.next_run) nextRunText = `next ${nextRunLabel}`;
  else if (job.fire_at) nextRunText = `fire at ${fireAtLabel}`;

  return (
    <HandlerDetailLayout
      testId={`job-detail-${job.job_id}`}
      testIdPrefix="job"
      kindLabel={kindLabel}
      statusKind={jobKind}
      name={job.job_name}
      nameAutoHint={job.name_auto}
      subtitle={
        [job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null]
          .filter(Boolean)
          .join(" ") || null
      }
      registrationSource={job.registration_source}
      chips={<ScheduleChips job={job} />}
      extras={
        nextRunText ? (
          <div class={layoutStyles.nextRun} data-testid="job-next-run">
            <code class="ht-text-mono ht-text-sm ht-text-muted">{nextRunText}</code>
          </div>
        ) : undefined
      }
      sourceLocation={job.source_location}
      onViewCode={onSwitchToCode}
      error={
        jobKind === "err"
          ? {
              type: job.last_error_type ?? null,
              message: job.last_error_message ?? null,
              traceback: job.last_error_traceback ?? null,
            }
          : null
      }
      statsCells={buildJobStatsCells(job, lastExecutedLabel)}
      statsTestId="job-stats-row"
      executionHeading="executions"
      executionRecords={executions ?? []}
      executionKind="job"
      executionTableId={`execution-table-${job.job_id}`}
      executionLoading={loading}
      executionHasData={executions !== undefined}
    />
  );
}
