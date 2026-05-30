import clsx from "clsx";
import { useEffect, useRef } from "preact/hooks";
import { useLocation } from "wouter";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useCorrectUrl } from "../../hooks/use-correct-url";
import { BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { useSignal } from "../../hooks/use-signal";
import { Button } from "../shared/button";
import { EmptyState } from "../shared/empty-state";
import { HandlerList, type SelectedHandlerId } from "./handler-list";
import styles from "./handlers-tab.module.css";
import { HandlersHealthStrip } from "./health-strip";
import { JobDetail } from "./job-detail";
import { ListenerDetail } from "./listener-detail";

/** Parse a path-based handler segment like "listener/123" or "job/456". */
function parseSelectedHandler(raw: string | null): { kind: "listener" | "job"; id: number } | null {
  if (!raw) return null;
  const listenerMatch = /^listener\/(\d+)$/.exec(raw);
  if (listenerMatch) return { kind: "listener", id: parseInt(listenerMatch[1], 10) };
  const jobMatch = /^job\/(\d+)$/.exec(raw);
  if (jobMatch) return { kind: "job", id: parseInt(jobMatch[1], 10) };
  return null;
}

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  selectedHandler: string | null;
  appKey: string;
  instanceQs: string;
  onSwitchToCode?: (line?: number) => void;
}

function DetailContent({
  listener,
  job,
  onSwitchToCode,
}: {
  listener: ListenerData | null;
  job: JobData | null;
  onSwitchToCode?: (line?: number) => void;
}) {
  if (listener) return <ListenerDetail listener={listener} onSwitchToCode={onSwitchToCode} />;
  if (job) return <JobDetail job={job} onSwitchToCode={onSwitchToCode} />;
  return <EmptyState icon="←" title="Select a handler or job to see details." data-testid="detail-placeholder" />;
}

export function HandlersTab({ listeners, jobs, selectedHandler, appKey, instanceQs, onSwitchToCode }: Props) {
  const [, navigate] = useLocation();
  const correctUrl = useCorrectUrl();

  // ResizeObserver instead of useMediaQuery: breakpoint is relative to this container's width, not the viewport.
  const isMobile = useSignal(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isMobile.value = entry.contentRect.width < BREAKPOINT_MOBILE;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isMobile]);

  const hasItems = listeners.length > 0 || jobs.length > 0;

  const parsed = parseSelectedHandler(selectedHandler);

  const selectedListener =
    parsed?.kind === "listener" ? (listeners.find((l) => l.listener_id === parsed.id) ?? null) : null;
  const selectedJob = parsed?.kind === "job" ? (jobs.find((j) => j.job_id === parsed.id) ?? null) : null;

  useEffect(() => {
    if (!selectedHandler || !parsed) return;
    if (!hasItems) return;
    const found =
      parsed.kind === "listener"
        ? listeners.some((l) => l.listener_id === parsed.id)
        : jobs.some((j) => j.job_id === parsed.id);
    if (!found) {
      correctUrl(`/apps/${appKey}/handlers${instanceQs}`);
    }
  }, [selectedHandler, parsed, hasItems, listeners, jobs, appKey, instanceQs, correctUrl]);

  const handleSelect = (id: SelectedHandlerId) => {
    const segment = id.kind === "listener" ? `listener/${id.id}` : `job/${id.id}`;
    navigate(`/apps/${appKey}/handlers/${segment}${instanceQs}`);
  };

  if (!hasItems) {
    return (
      <div data-testid="handlers-empty">
        <EmptyState title="no handlers or scheduled jobs registered." />
      </div>
    );
  }

  const showMobileDetail = isMobile.value && selectedHandler !== null;
  const showMasterList = !isMobile.value || selectedHandler === null;
  const showDetailPane = !isMobile.value || selectedHandler !== null;

  const selectedId: SelectedHandlerId | null = parsed ? { kind: parsed.kind, id: parsed.id } : null;

  return (
    <div ref={containerRef} class={styles.container}>
      <HandlersHealthStrip listeners={listeners} jobs={jobs} />

      {showMobileDetail && (
        <Button
          ghost
          size="sm"
          class="ht-mb-3"
          data-testid="back-to-list"
          onClick={() => navigate(`/apps/${appKey}/handlers${instanceQs}`)}
          aria-label="Back to handler list"
        >
          ← back
        </Button>
      )}

      <div class={clsx(styles.masterDetail, isMobile.value && styles.masterDetailMobile)}>
        {showMasterList && (
          <div class={styles.masterDetailList}>
            <HandlerList listeners={listeners} jobs={jobs} selectedId={selectedId} onSelect={handleSelect} />
          </div>
        )}

        {showDetailPane && (
          <div class={styles.masterDetailDetail}>
            <DetailContent listener={selectedListener} job={selectedJob} onSwitchToCode={onSwitchToCode} />
          </div>
        )}
      </div>
    </div>
  );
}
