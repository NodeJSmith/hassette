import { ExecutionLogs } from "./execution-logs";
import { formatDuration } from "../../utils/format";
import styles from "./detail-panel.module.css";

function splitTraceback(tb: string): { frames: string; errorLine: string } | null {
  const lastNewline = tb.lastIndexOf("\n");
  if (lastNewline <= 0) return null;
  return { frames: tb.slice(0, lastNewline), errorLine: tb.slice(lastNewline + 1) };
}

interface Props {
  kind: "handler" | "job";
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
  kind,
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
  const bg = isError
    ? "var(--err-bg)"
    : isTimeout
      ? "var(--warn-bg)"
      : undefined;

  return (
    <div class={styles.panel} style={bg ? { background: bg } : undefined} data-testid={testId}>
      {context && (
        <div class={styles.context}>
          <span class={styles.label}>context</span>
          <span class="ht-text-mono ht-text-xs">{context.triggerContextId}</span>
          <span class="ht-text-mono ht-text-xs ht-text-muted">&middot; origin {context.triggerOrigin ?? "LOCAL"}</span>
        </div>
      )}

      <div class={styles.grid} data-testid={`${testId}-grid`}>
        <div>
          <span class={styles.label}>execution id</span>
          <div class={styles.codeBox}>
            <pre class="ht-text-mono">{executionId ?? "—"}</pre>
          </div>
        </div>
        <div>
          <span class={styles.label}>
            {isError ? "traceback" : isTimeout ? "timeout" : "result"}
          </span>
          <div class={styles.codeBox}>
            {isError && errorTraceback ? (() => {
              const split = splitTraceback(errorTraceback);
              return split ? (
                <pre class="ht-text-mono" data-testid={`${testId.replace("-detail", "")}-traceback`}>
                  <span class={styles.tracebackFrames}>{split.frames}</span>
                  {"\n"}
                  <span class={styles.tracebackError}>{split.errorLine}</span>
                </pre>
              ) : (
                <pre class="ht-text-mono ht-text-danger" data-testid={`${testId.replace("-detail", "")}-traceback`}>
                  {errorTraceback}
                </pre>
              );
            })() : isTimeout ? (
              <pre class="ht-text-mono ht-text-warning">
                {`${kind} exceeded ${formatDuration(durationMs)} budget\ntask cancelled by ${kind} runner`}
              </pre>
            ) : isError && errorMessage ? (
              <pre class="ht-text-mono ht-text-danger">
                {`${errorType ?? "Error"}: ${errorMessage}`}
              </pre>
            ) : (
              <pre class="ht-text-mono">completed in {formatDuration(durationMs)}</pre>
            )}
          </div>
        </div>
      </div>

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
