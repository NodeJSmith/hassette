import styles from "./detail-panel.module.css";
import { ErrorDisplay } from "./error-display";
import { ExecutionLogs } from "./execution-logs";
import { TracebackViewer } from "./traceback-viewer";

interface Props {
  status: string;
  durationMs: number;
  executionId?: string | null;
  errorType?: string | null;
  errorMessage?: string | null;
  errorTraceback?: string | null;
  triggerMode?: string | null;
  context?: {
    triggerContextId: string;
    triggerOrigin?: string | null;
  };
  testId: string;
}

export function DetailPanel({
  status,
  durationMs,
  executionId,
  errorType,
  errorMessage,
  errorTraceback,
  triggerMode,
  context,
  testId,
}: Props) {
  const hasTraceback = status === "error" && !!errorTraceback;

  return (
    <div class={styles.panel} data-testid={testId}>
      {triggerMode && (
        <div class={styles.metaItem}>
          <span class={styles.label}>trigger mode</span>
          <span class="ht-text-mono ht-text-xs">{triggerMode}</span>
        </div>
      )}

      {context && (
        <div class={styles.metaItem}>
          <span class={styles.label}>context</span>
          <span class="ht-text-mono ht-text-xs">{context.triggerContextId}</span>
          <span class="ht-text-mono ht-text-xs ht-text-muted">&middot; origin {context.triggerOrigin ?? "LOCAL"}</span>
        </div>
      )}

      <div class={styles.metaRow}>
        <div class={styles.metaItem}>
          <span class={styles.label}>execution id</span>
          <span class="ht-text-mono ht-text-xs">{executionId ?? "—"}</span>
        </div>
        {!hasTraceback && (
          <ErrorDisplay status={status} durationMs={durationMs} errorType={errorType} errorMessage={errorMessage} />
        )}
      </div>

      {hasTraceback && <TracebackViewer traceback={errorTraceback} testIdPrefix={testId.replace("-detail", "")} />}

      <div class={styles.logsWrapper}>
        {executionId ? (
          <ExecutionLogs executionId={executionId} />
        ) : (
          <div data-testid="execution-logs-fallback">
            <span class={styles.label}>logs</span>
            <p class={styles.logsMessage}>No execution ID — logs unavailable.</p>
          </div>
        )}
      </div>
    </div>
  );
}
