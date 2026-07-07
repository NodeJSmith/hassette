import type { JobData } from "../../api/endpoints";
import { getJobExecutions, triggerJob } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { useSignal } from "../../hooks/use-signal";
import { queryKeys } from "../../lib/query-keys";
import { useAppState } from "../../state/context";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { formatDurationOrDash, formatOptionalDuration, formatTriggerDetail } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { Button } from "../shared/button";
import { Chip } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import { IconPlay } from "../shared/icons";
import { Spinner } from "../shared/spinner";
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

function RunNowButton({ jobId }: { jobId: number }) {
  const loading = useSignal(false);
  const error = useSignal<string | null>(null);

  const exec = async () => {
    if (loading.value) return;
    error.value = null;
    loading.value = true;
    try {
      await triggerJob(jobId);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  };

  return (
    <div class={layoutStyles.runNow}>
      <Button
        variant="primary"
        size="sm"
        data-testid="run-now-btn"
        disabled={loading.value}
        onClick={() => void exec()}
      >
        {loading.value ? (
          <>
            <Spinner /> Running…
          </>
        ) : (
          <>
            <IconPlay /> Run Now
          </>
        )}
      </Button>
      {error.value && (
        <p class="ht-text-danger ht-text-sm" role="alert" data-testid="run-now-error">
          {error.value}
        </p>
      )}
    </div>
  );
}

function buildJobStatsCells(job: JobData, lastExecutedLabel: string): DetailStatsCell[] {
  const cells: DetailStatsCell[] = [
    { label: "Runs", value: job.total_executions },
    { label: "Successful", value: job.successful },
    { label: "Last", value: job.last_executed_at ? lastExecutedLabel || "—" : "—" },
    { label: "Failed", value: job.failed, tone: job.failed > 0 ? "err" : undefined },
    { label: "Timed Out", value: job.timed_out, tone: job.timed_out > 0 ? "warn" : undefined },
  ];
  if (job.cancelled > 0) cells.push({ label: "Cancelled", value: job.cancelled, tone: "cancel" });
  if (job.skipped > 0) cells.push({ label: "Skipped", value: job.skipped, tone: "mute" });
  cells.push({ label: "Mode", value: job.mode });
  if (job.thread_leaked > 0) cells.push({ label: "Thread Leaked", value: job.thread_leaked, tone: "warn" });
  if (job.suppressed_count > 0) cells.push({ label: "Suppressed", value: job.suppressed_count, tone: "mute" });
  if (job.dropped_count > 0) cells.push({ label: "Dropped", value: job.dropped_count, tone: "warn" });
  cells.push(
    { label: "Min", value: formatOptionalDuration(job.min_duration_ms) },
    { label: "Avg", value: formatDurationOrDash(job.avg_duration_ms) },
    { label: "Max", value: formatOptionalDuration(job.max_duration_ms) },
  );
  return cells;
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
    (events) => events?.some((e) => e.kind === "job" && e.job_id === job.job_id) ?? false,
    queryKeys.jobExecutions(job.job_id),
  );

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);
  const jobKind = jobHealthKind(job);
  const predicateDescription = job.human_description || job.predicate_description || null;

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
        <>
          {predicateDescription && (
            <p class={layoutStyles.subtitle} data-testid="job-predicate-description">
              {predicateDescription}
            </p>
          )}
          {nextRunText && (
            <div class={layoutStyles.nextRun} data-testid="job-next-run">
              <code class="ht-text-mono ht-text-sm ht-text-muted">{nextRunText}</code>
            </div>
          )}
          <RunNowButton jobId={job.job_id} />
        </>
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
