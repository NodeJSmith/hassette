import type { CSSProperties } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useCorrectUrl } from "../../hooks/use-correct-url";
import { BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { appHandlersPath, handlerPath } from "../../utils/app-routes";
import { EmptyState } from "../shared/empty-state";
import { ExecutionDetailFetcher } from "./execution-detail";
import { HandlerList, type SelectedHandlerId } from "./handler-list";
import { JobDetail } from "./job-detail";
import { ListenerDetail } from "./listener-detail";

/** Parse a path-based handler segment like "listener/123" or "job/456". */
function parseSelectedHandler(raw: string | null): SelectedHandlerId | null {
  if (!raw) return null;
  const listenerMatch = /^listener\/(\d+)$/.exec(raw);
  if (listenerMatch) return { kind: "listener", id: parseInt(listenerMatch[1], 10) };
  const jobMatch = /^job\/(\d+)$/.exec(raw);
  if (jobMatch) return { kind: "job", id: parseInt(jobMatch[1], 10) };
  return null;
}

type ContentMode =
  | { mode: "execution-detail"; parsed: SelectedHandlerId; execId: string }
  | { mode: "empty" }
  | { mode: "master-detail"; parsed: SelectedHandlerId | null };

function deriveContentMode(
  selectedExecId: string | null,
  parsed: SelectedHandlerId | null,
  hasItems: boolean,
): ContentMode {
  if (selectedExecId && parsed) return { mode: "execution-detail", parsed, execId: selectedExecId };
  if (!hasItems) return { mode: "empty" };
  return { mode: "master-detail", parsed };
}

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  selectedHandler: string | null;
  selectedExecId: string | null;
  appKey: string;
  instanceIndex?: number;
  onSwitchToCode?: (line?: number) => void;
}

function DetailContent({
  listener,
  job,
  appKey,
  instanceQs,
  onSwitchToCode,
}: {
  listener: ListenerData | null;
  job: JobData | null;
  appKey: string;
  instanceQs?: string;
  onSwitchToCode?: (line?: number) => void;
}) {
  if (listener)
    return (
      <ListenerDetail listener={listener} appKey={appKey} instanceQs={instanceQs} onSwitchToCode={onSwitchToCode} />
    );
  if (job) return <JobDetail job={job} appKey={appKey} instanceQs={instanceQs} onSwitchToCode={onSwitchToCode} />;
  return <EmptyState icon="←" title="Select a handler or job to see details." data-testid="detail-placeholder" />;
}

export function HandlersTab({
  listeners,
  jobs,
  selectedHandler,
  selectedExecId,
  appKey,
  instanceIndex,
  onSwitchToCode,
}: Props) {
  const [, navigate] = useLocation();
  const correctUrl = useCorrectUrl();

  // ResizeObserver instead of useMediaQuery: breakpoint is relative to this container's width, not the viewport.
  // Callback ref (not useRef + useEffect) so the observer attaches/detaches whenever the root node changes,
  // regardless of which contentMode branch renders it.
  const [isMobile, setIsMobile] = useState(false);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  const containerRef = useCallback((el: HTMLDivElement | null) => {
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setIsMobile(entry.contentRect.width < BREAKPOINT_MOBILE);
      }
    });
    ro.observe(el);
    resizeObserverRef.current = ro;
  }, []);

  const hasItems = listeners.length > 0 || jobs.length > 0;
  const instanceQs = instanceIndex !== undefined ? `?instance=${instanceIndex}` : "";

  const parsed = parseSelectedHandler(selectedHandler);

  const selectedListener =
    parsed?.kind === "listener" ? (listeners.find((l) => l.listener_id === parsed.id) ?? null) : null;
  const selectedJob = parsed?.kind === "job" ? (jobs.find((j) => j.job_id === parsed.id) ?? null) : null;

  useEffect(() => {
    if (!selectedHandler || !parsed) return;
    if (selectedExecId) return;
    if (!hasItems) return;
    const found =
      parsed.kind === "listener"
        ? listeners.some((l) => l.listener_id === parsed.id)
        : jobs.some((j) => j.job_id === parsed.id);
    if (!found) {
      correctUrl(appHandlersPath(appKey, { instance: instanceIndex }));
    }
  }, [selectedHandler, parsed, selectedExecId, hasItems, listeners, jobs, appKey, instanceIndex, correctUrl]);

  const handleSelect = (id: SelectedHandlerId) => {
    navigate(handlerPath(appKey, id.kind, id.id, { instance: instanceIndex }));
  };

  const contentMode = deriveContentMode(selectedExecId, parsed, hasItems);

  switch (contentMode.mode) {
    case "execution-detail": {
      return (
        <div ref={containerRef}>
          <ExecutionDetailFetcher executionId={contentMode.execId} />
        </div>
      );
    }

    case "empty":
      return (
        <div ref={containerRef} data-testid="handlers-empty">
          <EmptyState title="no handlers or scheduled jobs registered." />
        </div>
      );

    case "master-detail": {
      const showMobileDetail = isMobile && selectedHandler !== null;
      const showMasterList = !isMobile || selectedHandler === null;
      const showDetailPane = !isMobile || selectedHandler !== null;

      const selectedId: SelectedHandlerId | null = parsed ? { kind: parsed.kind, id: parsed.id } : null;

      return (
        <div ref={containerRef} className="flex flex-col gap-4">
          {showMobileDetail && (
            <Button
              variant="ghost"
              size="sm"
              data-testid="back-to-list"
              onClick={() => navigate(appHandlersPath(appKey, { instance: instanceIndex }))}
              aria-label="Back to handler list"
            >
              ← back
            </Button>
          )}

          <div
            className={cn(
              "grid items-start gap-4 [grid-template-columns:minmax(var(--master-min-width),var(--master-max-width))_1fr]",
              isMobile && "block",
            )}
            style={
              {
                "--master-min-width": "240px",
                "--master-max-width": "340px",
                "--master-max-height": "70vh",
              } as CSSProperties
            }
          >
            {showMasterList && (
              <div
                className={cn(
                  "max-h-[var(--master-max-height)] overflow-y-auto rounded-md border border-border bg-card",
                  isMobile && "mb-4 max-h-none",
                )}
              >
                <HandlerList listeners={listeners} jobs={jobs} selectedId={selectedId} onSelect={handleSelect} />
              </div>
            )}

            {showDetailPane && (
              <div className="overflow-y-auto">
                <DetailContent
                  listener={selectedListener}
                  job={selectedJob}
                  appKey={appKey}
                  instanceQs={instanceQs}
                  onSwitchToCode={onSwitchToCode}
                />
              </div>
            )}
          </div>
        </div>
      );
    }

    default: {
      const _exhaustive: never = contentMode;
      return _exhaustive;
    }
  }
}
