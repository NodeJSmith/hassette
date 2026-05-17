import type { JobData } from "../../api/endpoints";
import { getJobExecutions } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-filtered-signal-refetch";
import { formatTriggerDetail, formatOptionalDuration, formatDurationOrDash } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { jobStatusKind } from "./handler-list";
import { Chip } from "../shared/chip";
import { HandlerDetailLayout } from "./handler-detail-layout";
import type { DetailStatsCell } from "../shared/detail-stats";
import chipStyles from "./handler-chips.module.css";

function ScheduleChips({ job }: { job: JobData }) {
  const chips: Array<{ label: string }> = [];
  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  if (chips.length === 0) return null;
  return (
    <div class={chipStyles.chipRow} data-testid="schedule-chips">
      {chips.map((chip) => (
        <Chip key={chip.label} variant="schedule">{chip.label}</Chip>
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
    { label: "Timed Out", value: job.timed_out > 0 ? job.timed_out : "—", tone: job.timed_out > 0 ? "warn" : undefined },
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
  const { data: executions, loading, refetch } = useScopedApi(
    (since) => getJobExecutions(job.job_id, 50, since),
    { deps: [job.job_id] },
  );

  const { executionCompleted } = useAppState();
  const lastExecutedLabel = useRelativeTime(job.last_executed_at);
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const fireAtLabel = useRelativeTime(job.fire_at ?? null);

  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events?.some((e) => e.job_id === job.job_id) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);
  const jobKind = jobStatusKind(job);

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
      subtitle={[job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null].filter(Boolean).join(" ") || null}
      registrationSource={job.registration_source}
      chips={<ScheduleChips job={job} />}
      extras={nextRunText ? (
        <div style={{ marginBottom: "var(--sp-3)" }} data-testid="job-next-run">
          <code class="ht-text-mono ht-text-sm ht-text-muted">{nextRunText}</code>
        </div>
      ) : undefined}
      sourceLocation={job.source_location}
      onViewCode={onSwitchToCode}
      error={jobKind === "err" ? {
        type: job.last_error_type ?? null,
        message: job.last_error_message ?? null,
        traceback: job.last_error_traceback ?? null,
      } : null}
      statsCells={buildJobStatsCells(job, lastExecutedLabel)}
      statsTestId="job-stats-row"
      executionHeading="executions"
      executionRecords={executions.value ?? []}
      executionKind="job"
      executionTableId={`execution-table-${job.job_id}`}
      executionLoading={loading}
      executionHasData={!!executions.value}
    />
  );
}
