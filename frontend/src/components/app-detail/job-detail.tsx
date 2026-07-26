import type { JobData } from "../../api/endpoints";
import { getJobExecutions, triggerJob } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppState } from "../../state/context";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { formatTriggerDetail } from "../../utils/format";
import { handlerKindLabel } from "../../utils/status";
import { Button } from "../shared/button";
import { Chip } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import { DetailStats } from "../shared/detail-stats";
import { ErrorBanner } from "../shared/error-banner";
import { IconPlay } from "../shared/icons";
import { Spinner } from "../shared/spinner";
import { DetailHeader } from "./detail-header";
import { ExecutionSection } from "./execution-section";
import chipStyles from "./handler-chips.module.css";
import { HandlerDetailLayout } from "./handler-detail-layout";
import layoutStyles from "./handler-detail-layout.module.css";
import { jobHealthKind } from "./handler-list";
import { HandlerModeChip } from "./handler-mode-chip";
import styles from "./job-detail.module.css";
import { RegistrationFooter } from "./registration-footer";
import { buildCommonStatCells, type CommonStatInput } from "./stat-cell-builders";

function ScheduleChips({ job }: { job: JobData }) {
  const chips: Array<{ label: string }> = [];
  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  return (
    <div class={chipStyles.chipRow} data-testid="schedule-chips">
      <HandlerModeChip mode={job.mode} />
      {chips.map((chip) => (
        <Chip key={chip.label} variant="job">
          {chip.label}
        </Chip>
      ))}
    </div>
  );
}

function RunNowButton({ jobId }: { jobId: number }) {
  const { loading, error, run } = useAsyncAction();

  return (
    <div class={layoutStyles.runNow}>
      <Button
        variant="primary"
        size="sm"
        data-testid="run-now-btn"
        disabled={loading.value}
        onClick={() => void run(() => triggerJob(jobId))}
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

function buildJobStatsCells(job: JobData, lastExecutedLabel: string, nextRunText: string | null): DetailStatsCell[] {
  const input: CommonStatInput = {
    totalLabel: "Runs",
    total: job.total_executions,
    failed: job.failed,
    avgDurationMs: job.avg_duration_ms,
    lastLabel: nextRunText ?? (job.last_executed_at ? lastExecutedLabel || "—" : "—"),
    lastFieldLabel: nextRunText ? "Next" : "Last",
    timedOut: job.timed_out,
    cancelled: job.cancelled,
    threadLeaked: job.thread_leaked,
    suppressedCount: job.suppressed_count,
    droppedCount: job.dropped_count,
    insertAfterCancelledOrTimedOut:
      job.skipped > 0 ? { label: "Skipped", value: job.skipped, tone: "mute" } : undefined,
  };
  return buildCommonStatCells(input);
}

interface Props {
  job: JobData;
  appKey: string;
  instanceQs?: string;
  onSwitchToCode?: (line?: number) => void;
}

export function JobDetail({ job, appKey, instanceQs, onSwitchToCode }: Props) {
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
    <HandlerDetailLayout testId={`job-detail-${job.job_id}`}>
      <DetailHeader
        name={job.job_name}
        kindLabel={kindLabel}
        statusKind={jobKind}
        kind="job"
        subtitle={
          [job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null]
            .filter(Boolean)
            .join(" ") || null
        }
        headerActions={<RunNowButton jobId={job.job_id} />}
      />

      {predicateDescription && (
        <p class={styles.predicateDescription} data-testid="job-predicate-description">
          {predicateDescription}
        </p>
      )}

      <ScheduleChips job={job} />

      {jobKind === "err" && (job.last_error_message || job.last_error_type) && (
        <ErrorBanner
          errorType={job.last_error_type ?? null}
          errorMessage={job.last_error_message ?? null}
          traceback={job.last_error_traceback ?? null}
          data-testid="job-error-banner"
        />
      )}

      <DetailStats cells={buildJobStatsCells(job, lastExecutedLabel, nextRunText)} data-testid="job-stats-row" />

      <ExecutionSection
        heading="executions"
        records={executions}
        kind="job"
        tableId={`execution-table-${job.job_id}`}
        loading={loading}
        appKey={appKey}
        handlerKind="job"
        handlerId={job.job_id}
        instanceQs={instanceQs}
      />

      <RegistrationFooter
        kind="job"
        testId={`job-detail-${job.job_id}`}
        sourceLocation={job.source_location}
        registrationSource={job.registration_source}
        onViewCode={onSwitchToCode}
      />
    </HandlerDetailLayout>
  );
}
