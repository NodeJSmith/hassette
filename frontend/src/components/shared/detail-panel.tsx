import { ExecutionLogs } from "./execution-logs";
import { formatDuration } from "../../utils/format";
import styles from "./detail-panel.module.css";

function splitTraceback(tb: string): { frames: string; errorLine: string } | null {
  const trimmed = tb.trimEnd();
  const lastNewline = trimmed.lastIndexOf("\n");
  if (lastNewline <= 0) return null;
  return { frames: trimmed.slice(0, lastNewline), errorLine: trimmed.slice(lastNewline + 1) };
}

interface Props {
  status: string;
  durationMs: number;
  executionId?: string | null;
  errorType?: string | null;
  errorMessage?: string | null;
  errorTraceback?: string | null;
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
  context,
  testId,
}: Props) {
  const isError = status === "error";
  const isTimeout = status === "timed_out";
  const hasTraceback = isError && errorTraceback;

  return (
    <div class={styles.panel} data-testid={testId}>
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
          <div class={styles.metaItem}>
            <span class={styles.label}>
              {isTimeout ? "timeout" : "result"}
            </span>
            {isTimeout ? (
              <span class="ht-text-mono ht-text-xs ht-text-warning">
                exceeded {formatDuration(durationMs)} budget
              </span>
            ) : isError && errorMessage ? (
              <span class="ht-text-mono ht-text-xs ht-text-danger">
                {errorType ?? "Error"}: {errorMessage}
              </span>
            ) : (
              <span class="ht-text-mono ht-text-xs">
                completed in {formatDuration(durationMs)}
              </span>
            )}
          </div>
        )}
      </div>

      {hasTraceback && (
        <div class={styles.tracebackSection}>
          <span class={styles.label}>traceback</span>
          {(() => {
            const split = splitTraceback(errorTraceback);
            return split ? (
              <>
                <div class={styles.errorLine}>
                  <pre class="ht-text-mono">{split.errorLine}</pre>
                </div>
                <pre class={styles.tracebackFrames} data-testid={`${testId.replace("-detail", "")}-traceback`}>
                  {split.frames}
                </pre>
              </>
            ) : (
              <pre class="ht-text-mono ht-text-danger" data-testid={`${testId.replace("-detail", "")}-traceback`}>
                {errorTraceback}
              </pre>
            );
          })()}
        </div>
      )}

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
