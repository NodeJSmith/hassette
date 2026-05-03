import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { ListenerData, JobData } from "../../api/endpoints";
import { getHandlerInvocations, getJobExecutions } from "../../api/endpoints";
import { HandlerList, type SelectedHandlerId } from "./handler-list";
import { HandlerInvocations } from "./handler-invocations";
import { JobExecutions } from "./job-executions";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useDebouncedEffect } from "../../hooks/use-debounced-effect";
import { formatTriggerDetail } from "../../utils/format";
import { useRelativeTime } from "../../hooks/use-relative-time";

const MOBILE_BREAKPOINT = 768;

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  focusMethod: string | null;
}

/** Inline chips for listener modifier options. */
function ModifierChips({ listener }: { listener: ListenerData }) {
  const chips: Array<{ label: string; value?: string }> = [];
  if (listener.debounce) chips.push({ label: "debounce", value: `${listener.debounce * 1000}ms` });
  if (listener.throttle) chips.push({ label: "throttle", value: `${listener.throttle * 1000}ms` });
  if (listener.once) chips.push({ label: "once" });
  if (listener.priority) chips.push({ label: "priority", value: String(listener.priority) });
  if (listener.immediate) chips.push({ label: "immediate" });
  if (listener.duration) chips.push({ label: "duration", value: `${listener.duration}s` });

  if (chips.length === 0) return null;
  return (
    <div class="ht-chip-row" data-testid="modifier-chips">
      {chips.map((c) => (
        <span key={c.label} class="ht-chip ht-chip--modifier">
          {c.label}{c.value ? ` ${c.value}` : ""}
        </span>
      ))}
    </div>
  );
}

/** Inline chips for job schedule configuration. */
function ScheduleChips({ job }: { job: JobData }) {
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const fireAtLabel = useRelativeTime(job.fire_at ?? null);

  const chips: Array<{ label: string }> = [];

  if (job.trigger_label) chips.push({ label: job.trigger_label });
  if (job.trigger_detail) chips.push({ label: formatTriggerDetail(job.trigger_detail) });
  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  return (
    <div class="ht-chip-row" data-testid="schedule-chips">
      {chips.map((c, i) => (
        <span key={i} class="ht-chip ht-chip--schedule">{c.label}</span>
      ))}
      {nextRunLabel && (
        <span key="next-run" class="ht-chip ht-chip--schedule">next: {nextRunLabel}</span>
      )}
      {fireAtLabel && (
        <span key="fire-at" class="ht-chip ht-chip--schedule">fire at: {fireAtLabel}</span>
      )}
    </div>
  );
}

interface ListenerDetailProps {
  listener: ListenerData;
}

function ListenerDetail({ listener }: ListenerDetailProps) {
  const { data: invocations, loading, refetch } = useScopedApi(
    (since) => getHandlerInvocations(listener.listener_id, 50, since),
    { deps: [listener.listener_id] },
  );

  const { invocationCompleted } = useAppState();

  // Targeted real-time refetch when a matching invocation_completed event arrives
  useDebouncedEffect(
    () => invocationCompleted.value,
    500,
    () => {
      const events = invocationCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.listener_id === listener.listener_id);
      if (matches) void refetch();
    },
  );

  return (
    <div class="ht-detail-pane__content" data-testid={`listener-detail-${listener.listener_id}`}>
      <div class="ht-detail-pane__meta">
        <span class="ht-detail-label">Handler</span>
        <code class="ht-text-mono">{listener.handler_method}</code>
      </div>
      <ModifierChips listener={listener} />
      {loading.value && !invocations.value ? (
        <p class="ht-text-muted ht-text-xs">Loading invocations…</p>
      ) : (
        <HandlerInvocations
          invocations={invocations.value ?? []}
          listenerId={listener.listener_id}
        />
      )}
    </div>
  );
}

interface JobDetailProps {
  job: JobData;
}

function JobDetail({ job }: JobDetailProps) {
  const { data: executions, loading, refetch } = useScopedApi(
    (since) => getJobExecutions(job.job_id, 50, since),
    { deps: [job.job_id] },
  );

  const { executionCompleted } = useAppState();

  // Targeted real-time refetch when a matching execution_completed event arrives
  useDebouncedEffect(
    () => executionCompleted.value,
    500,
    () => {
      const events = executionCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.job_id === job.job_id);
      if (matches) void refetch();
    },
  );

  return (
    <div class="ht-detail-pane__content" data-testid={`job-detail-${job.job_id}`}>
      <div class="ht-detail-pane__meta">
        <span class="ht-detail-label">Job</span>
        <code class="ht-text-mono">{job.job_name}</code>
      </div>
      <ScheduleChips job={job} />
      {loading.value && !executions.value ? (
        <p class="ht-text-muted ht-text-xs">Loading executions…</p>
      ) : (
        <JobExecutions
          executions={executions.value ?? []}
          jobId={job.job_id}
        />
      )}
    </div>
  );
}

export function HandlersTab({ listeners, jobs, focusMethod }: Props) {
  // Selected item in master list
  const selectedId = useRef(signal<SelectedHandlerId | null>(null)).current;
  // Mobile mode: show detail instead of list
  const showDetail = useRef(signal(false)).current;
  // Whether we're in mobile layout (< MOBILE_BREAKPOINT px)
  const isMobile = useRef(signal(false)).current;

  const containerRef = useRef<HTMLDivElement>(null);

  // ResizeObserver-based mobile detection (not media queries)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isMobile.value = entry.contentRect.width < MOBILE_BREAKPOINT;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isMobile]);

  // Auto-select based on focusMethod
  useEffect(() => {
    if (!focusMethod) return;
    const match = listeners.find((l) => l.handler_method.includes(focusMethod));
    if (match) {
      selectedId.value = { kind: "listener", id: match.listener_id };
      if (isMobile.value) showDetail.value = true;
    }
  }, [focusMethod, listeners, selectedId, isMobile, showDetail]);

  const handleSelect = (id: SelectedHandlerId) => {
    selectedId.value = id;
    if (isMobile.value) showDetail.value = true;
  };

  const handleBack = () => {
    showDetail.value = false;
  };

  const hasItems = listeners.length > 0 || jobs.length > 0;

  if (!hasItems) {
    return (
      <div class="ht-handlers-tab" data-testid="handlers-empty">
        <p class="ht-text-muted">No handlers or scheduled jobs registered.</p>
      </div>
    );
  }

  // Resolve selected item
  const selectedListener = selectedId.value?.kind === "listener"
    ? listeners.find((l) => l.listener_id === selectedId.value!.id) ?? null
    : null;
  const selectedJob = selectedId.value?.kind === "job"
    ? jobs.find((j) => j.job_id === selectedId.value!.id) ?? null
    : null;

  const showMobileDetail = isMobile.value && showDetail.value;
  const showMasterList = !isMobile.value || !showDetail.value;
  const showDetailPane = !isMobile.value || showDetail.value;

  return (
    <div class="ht-handlers-tab" ref={containerRef}>
      {/* Mobile: back button in detail view */}
      {showMobileDetail && (
        <button
          type="button"
          class="ht-btn ht-btn--ghost ht-btn--sm ht-mb-3"
          data-testid="back-to-list"
          onClick={handleBack}
          aria-label="Back to handler list"
        >
          ← Back
        </button>
      )}

      <div class={`ht-master-detail${isMobile.value ? " ht-master-detail--mobile" : ""}`}>
        {/* Master list */}
        {showMasterList && (
          <div class="ht-master-detail__list">
            <HandlerList
              listeners={listeners}
              jobs={jobs}
              selectedId={selectedId.value}
              onSelect={handleSelect}
            />
          </div>
        )}

        {/* Detail pane */}
        {showDetailPane && (
          <div class="ht-master-detail__detail">
            {selectedListener ? (
              <ListenerDetail listener={selectedListener} />
            ) : selectedJob ? (
              <JobDetail job={selectedJob} />
            ) : (
              <div class="ht-detail-pane__empty" data-testid="detail-placeholder">
                <p class="ht-text-muted">Select a handler or job to see details.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
