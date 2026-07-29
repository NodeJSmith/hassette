import { useQuery } from "@tanstack/react-query";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";

import type { ExecutionData } from "../../api/endpoints";
import { getExecutionById } from "../../api/endpoints";
import { useDocumentTitle } from "../../hooks/use-document-title";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatTimestamp, truncateId } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import type { DetailStatsCell } from "../shared/detail-stats";
import { DetailStats } from "../shared/detail-stats";
import { EmptyState } from "../shared/empty-state";
import { ErrorDisplay } from "../shared/error-display";
import { ExecutionLogs } from "../shared/execution-logs";
import { COPY_CONFIRM_MS } from "../shared/log-table/constants";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import { TracebackViewer } from "../shared/traceback-viewer";

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
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(
    async (e: ReactMouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, COPY_CONFIRM_MS);
      } catch {
        /* clipboard unavailable */
      }
    },
    [text],
  );

  return (
    <button
      type="button"
      className="shrink-0 rounded-sm border border-subtle px-1 py-0 text-xs leading-none text-muted-foreground hover:border-border hover:text-foreground"
      onClick={handleCopy}
      aria-label="Copy execution ID"
      title={copied ? "Copied" : "Copy execution ID"}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}

interface ContentProps {
  record: ExecutionData;
}

export function ExecutionDetailContent({ record }: ContentProps) {
  const truncated = truncateId(record.execution_id);
  const statusKind = executionStatusKind(record.status);
  const hasTraceback = record.status === "error" && !!record.error_traceback;

  useDocumentTitle(truncated ? `Execution ${truncated}` : "Execution");

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <StatusShape kind={statusKind} size={STATUS_DOT_SIZE} />
        <h2 className="m-0 font-mono text-[length:var(--text-h3)] font-semibold text-foreground">
          Execution {truncated}
        </h2>
        <StatusBadge status={record.status} threadLeaked={record.thread_leaked} />
      </div>

      {record.execution_id && (
        <div className="mb-4 flex items-center gap-1">
          <code className="break-all font-mono text-xs text-muted-foreground" title={record.execution_id}>
            {record.execution_id}
          </code>
          <CopyIdButton text={record.execution_id} />
        </div>
      )}

      <div className="mb-4">
        <DetailStats cells={buildMetaCells(record)} data-testid="execution-meta-stats" />
      </div>

      {(record.trigger_mode || record.trigger_context_id) && (
        <div className="mb-4">
          <h3 className="mb-2 font-sans text-sm font-semibold text-foreground">trigger</h3>
          <div className="flex gap-6 font-mono text-xs">
            {record.trigger_mode && (
              <div>
                <span className="mr-1 text-foreground-faint">mode</span>
                <span className="text-foreground">{record.trigger_mode}</span>
              </div>
            )}
            {record.trigger_context_id && (
              <div>
                <span className="mr-1 text-foreground-faint">context</span>
                <span className="text-foreground">{truncateId(record.trigger_context_id)}</span>
              </div>
            )}
            {record.trigger_origin && (
              <div>
                <span className="mr-1 text-foreground-faint">origin</span>
                <span className="text-foreground">{record.trigger_origin}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {hasTraceback && (
        <div className="mb-4">
          <TracebackViewer traceback={record.error_traceback!} testIdPrefix="execution" />
        </div>
      )}

      {!hasTraceback && record.status !== "success" && (
        <div className="mb-4">
          <ErrorDisplay
            status={record.status}
            durationMs={record.duration_ms}
            errorType={record.error_type}
            errorMessage={record.error_message}
          />
        </div>
      )}

      {record.status === "success" && (
        <div className="mb-4 flex items-center gap-2 rounded-sm bg-[var(--status-success-bg)] px-3 py-2">
          <StatusShape kind="ok" size={STATUS_DOT_SIZE} />
          <span className="font-mono text-sm text-foreground-secondary">
            completed in {formatDuration(record.duration_ms)}
          </span>
        </div>
      )}

      <div className="mb-4">
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
  executionId: string;
}

export function ExecutionDetailFetcher({ executionId }: FetcherProps) {
  const {
    data: record,
    isPending,
    isError,
  } = useQuery({
    queryKey: ["execution-detail", executionId],
    queryFn: ({ signal }) => getExecutionById(executionId, signal),
  });

  if (isPending) return <Spinner />;

  if (isError) {
    return <EmptyState title="failed to load execution" body="Could not fetch execution data. Try again later." />;
  }

  if (!record) {
    return <EmptyState title="execution not found" body="This execution may have expired from the telemetry window." />;
  }

  return <ExecutionDetailContent record={record} />;
}
