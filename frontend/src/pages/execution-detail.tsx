import { useQuery } from "@tanstack/preact-query";
import clsx from "clsx";
import { useCallback } from "preact/hooks";
import { Link } from "wouter";

import type { ExecutionData } from "../api/endpoints";
import { getExecutionById } from "../api/endpoints";
import { Badge } from "../components/shared/badge";
import type { DetailStatsCell } from "../components/shared/detail-stats";
import { DetailStats } from "../components/shared/detail-stats";
import { EmptyState } from "../components/shared/empty-state";
import { ErrorDisplay } from "../components/shared/error-display";
import { ExecutionLogs } from "../components/shared/execution-logs";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";
import { TracebackViewer } from "../components/shared/traceback-viewer";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useSignal } from "../hooks/use-signal";
import { useSubscribe } from "../hooks/use-subscribe";
import { STATUS_DOT_SIZE } from "../utils/constants";
import { formatDuration, formatTimestamp, truncateId } from "../utils/format";
import { executionStatusKind } from "../utils/status";
import styles from "./execution-detail.module.css";

function buildMetaCells(record: ExecutionData): DetailStatsCell[] {
  return [
    { label: "Duration", value: formatDuration(record.duration_ms) },
    { label: "Timestamp", value: formatTimestamp(record.execution_start_ts) },
    { label: "Status", value: record.status, tone: executionStatusKind(record.status) },
  ];
}

function StatusBadge({ status, threadLeaked }: { status: string; threadLeaked: boolean }) {
  return (
    <>
      {status === "error" && (
        <Badge variant="danger" size="sm">
          failed
        </Badge>
      )}
      {status === "timed_out" && (
        <Badge variant="warning" size="sm">
          timed out
        </Badge>
      )}
      {status === "cancelled" && (
        <Badge variant="neutral" size="sm">
          cancelled
        </Badge>
      )}
      {threadLeaked && (
        <Badge variant="warning" size="sm">
          thread leaked
        </Badge>
      )}
    </>
  );
}

function CopyIdButton({ text }: { text: string }) {
  const copied = useSignal(false);
  useSubscribe(copied);

  const handleCopy = useCallback(
    async (e: MouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        copied.value = true;
        setTimeout(() => {
          copied.value = false;
        }, 1500);
      } catch {
        /* clipboard unavailable */
      }
    },
    [text],
  );

  return (
    <button
      type="button"
      class={styles.copyBtn}
      onClick={handleCopy}
      aria-label="Copy execution ID"
      title={copied.value ? "Copied" : "Copy execution ID"}
    >
      {copied.value ? "✓" : "⧉"}
    </button>
  );
}

interface ContentProps {
  record: ExecutionData;
  backHref: string;
  handlerName?: string;
}

export function ExecutionDetailContent({ record, backHref, handlerName }: ContentProps) {
  const truncated = truncateId(record.execution_id);
  const statusKind = executionStatusKind(record.status);
  const hasTraceback = record.status === "error" && !!record.error_traceback;

  useDocumentTitle(truncated ? `Execution ${truncated}` : "Execution");

  return (
    <div>
      <Link href={backHref} class={styles.backLink}>
        ← back to {handlerName ?? "handler"}
      </Link>

      <div class={styles.header}>
        <StatusShape kind={statusKind} size={STATUS_DOT_SIZE} />
        <h2 class={styles.heading}>Execution {truncated}</h2>
        <StatusBadge status={record.status} threadLeaked={record.thread_leaked} />
      </div>

      {record.execution_id && (
        <div class={styles.fullId}>
          <code class={styles.idText} title={record.execution_id}>
            {record.execution_id}
          </code>
          <CopyIdButton text={record.execution_id} />
        </div>
      )}

      <div class={styles.section}>
        <DetailStats cells={buildMetaCells(record)} data-testid="execution-meta-stats" />
      </div>

      {(record.trigger_mode || record.trigger_context_id) && (
        <div class={styles.section}>
          <h3 class={styles.sectionHeading}>trigger</h3>
          <div class={styles.triggerGrid}>
            {record.trigger_mode && (
              <div>
                <span class={styles.triggerLabel}>mode</span>
                <span class={styles.triggerValue}>{record.trigger_mode}</span>
              </div>
            )}
            {record.trigger_context_id && (
              <div>
                <span class={styles.triggerLabel}>context</span>
                <span class={styles.triggerValue}>{truncateId(record.trigger_context_id)}</span>
              </div>
            )}
            {record.trigger_origin && (
              <div>
                <span class={styles.triggerLabel}>origin</span>
                <span class={styles.triggerValue}>{record.trigger_origin}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {hasTraceback && (
        <div class={styles.section}>
          <TracebackViewer traceback={record.error_traceback!} testIdPrefix="execution" />
        </div>
      )}

      {!hasTraceback && record.status !== "success" && (
        <div class={styles.section}>
          <ErrorDisplay
            status={record.status}
            durationMs={record.duration_ms}
            errorType={record.error_type}
            errorMessage={record.error_message}
          />
        </div>
      )}

      {record.status === "success" && (
        <div class={clsx(styles.section, styles.outcomeSuccess)}>
          <StatusShape kind="ok" size={STATUS_DOT_SIZE} />
          <span class={styles.outcomeText}>completed in {formatDuration(record.duration_ms)}</span>
        </div>
      )}

      <div class={styles.section}>
        {record.execution_id ? (
          <ExecutionLogs executionId={record.execution_id} />
        ) : (
          <EmptyState title="no execution ID" body="Logs unavailable without an execution ID." />
        )}
      </div>
    </div>
  );
}

interface FetcherProps {
  appKey: string;
  kind: "listener" | "job";
  handlerId: number;
  executionId: string;
  instanceQs: string;
  handlerName?: string;
}

export function ExecutionDetailFetcher({
  appKey,
  kind,
  handlerId,
  executionId,
  instanceQs,
  handlerName,
}: FetcherProps) {
  const {
    data: record,
    isPending,
    isError,
  } = useQuery({
    queryKey: ["execution-detail", executionId],
    queryFn: ({ signal }) => getExecutionById(executionId, signal),
  });
  const backHref = `/apps/${appKey}/handlers/${kind}/${handlerId}${instanceQs}`;

  if (isPending) return <Spinner />;

  if (isError) {
    return (
      <>
        <Link href={backHref} class={styles.backLink}>
          ← back to {handlerName ?? "handler"}
        </Link>
        <EmptyState title="failed to load execution" body="Could not fetch execution data. Try again later." />
      </>
    );
  }

  if (!record) {
    return (
      <>
        <Link href={backHref} class={styles.backLink}>
          ← back to {handlerName ?? "handler"}
        </Link>
        <EmptyState title="execution not found" body="This execution may have expired from the telemetry window." />
      </>
    );
  }

  return <ExecutionDetailContent record={record} backHref={backHref} handlerName={handlerName} />;
}
