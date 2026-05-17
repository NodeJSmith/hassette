import { useEffect, useRef } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import { useLocation } from "wouter";
import clsx from "clsx";
import type { ListenerData, JobData } from "../../api/endpoints";
import { HandlerList, type SelectedHandlerId } from "./handler-list";
import { HandlersHealthStrip } from "./health-strip";
import { useCorrectUrl } from "../../hooks/use-correct-url";
import { BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { EmptyState } from "../shared/empty-state";
import { Button } from "../shared/button";
import { ListenerDetail } from "./listener-detail";
import { JobDetail } from "./job-detail";
import styles from "./handlers-tab.module.css";

const LISTENER_URL_PREFIX = "h";
const JOB_URL_PREFIX = "j";
const HANDLER_PARAM_RE = /^([hj])-(\d+)$/;

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  selectedHandler: string | null;
  appKey: string;
  instanceQs: string;
  onSwitchToCode?: (line?: number) => void;
}

function parseHandlerParam(param: string): { kind: "listener" | "job"; id: number } | null {
  const match = HANDLER_PARAM_RE.exec(param);
  if (!match) return null;
  const id = parseInt(match[2], 10);
  if (match[1] === LISTENER_URL_PREFIX) return { kind: "listener", id };
  if (match[1] === JOB_URL_PREFIX) return { kind: "job", id };
  return null;
}

export function HandlersTab({ listeners, jobs, selectedHandler, appKey, instanceQs, onSwitchToCode }: Props) {
  const [, navigate] = useLocation();
  const correctUrl = useCorrectUrl();

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

  const parsed = selectedHandler ? parseHandlerParam(selectedHandler) : null;

  const selectedListener = parsed?.kind === "listener"
    ? listeners.find((l) => l.listener_id === parsed.id) ?? null
    : null;
  const selectedJob = parsed?.kind === "job"
    ? jobs.find((j) => j.job_id === parsed.id) ?? null
    : null;

  useEffect(() => {
    if (!selectedHandler || !parsed) return;
    if (!hasItems) return;
    const found = parsed.kind === "listener"
      ? listeners.some((l) => l.listener_id === parsed.id)
      : jobs.some((j) => j.job_id === parsed.id);
    if (!found) {
      correctUrl(`/apps/${appKey}/handlers${instanceQs}`);
    }
  }, [selectedHandler, parsed, hasItems, listeners, jobs, appKey, instanceQs, correctUrl]);

  const handleSelect = (id: SelectedHandlerId) => {
    const kindPrefix = id.kind === "listener" ? LISTENER_URL_PREFIX : JOB_URL_PREFIX;
    navigate(`/apps/${appKey}/handlers/${kindPrefix}-${id.id}${instanceQs}`);
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

  const selectedId: SelectedHandlerId | null = parsed
    ? { kind: parsed.kind, id: parsed.id }
    : null;

  return (
    <div ref={containerRef}>
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
            <HandlerList
              listeners={listeners}
              jobs={jobs}
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </div>
        )}

        {showDetailPane && (
          <div class={styles.masterDetailDetail}>
            {selectedListener ? (
              <ListenerDetail listener={selectedListener} onSwitchToCode={onSwitchToCode} />
            ) : selectedJob ? (
              <JobDetail job={selectedJob} onSwitchToCode={onSwitchToCode} />
            ) : (
              <EmptyState icon="←" title="Select a handler or job to see details." data-testid="detail-placeholder" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
