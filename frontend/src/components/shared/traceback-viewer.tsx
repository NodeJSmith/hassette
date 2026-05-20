import styles from "./detail-panel.module.css";

function splitTraceback(tb: string): { frames: string; errorLine: string } | null {
  const trimmed = tb.trimEnd();
  const lastNewline = trimmed.lastIndexOf("\n");
  if (lastNewline <= 0) return null;
  return { frames: trimmed.slice(0, lastNewline), errorLine: trimmed.slice(lastNewline + 1) };
}

interface Props {
  traceback: string;
  testIdPrefix: string;
}

export function TracebackViewer({ traceback, testIdPrefix }: Props) {
  const split = splitTraceback(traceback);

  return (
    <div class={styles.tracebackSection}>
      <span class={styles.label}>traceback</span>
      {split ? (
        <>
          <div class={styles.errorLine}>
            <pre class="ht-text-mono">{split.errorLine}</pre>
          </div>
          <pre class={styles.tracebackFrames} data-testid={`${testIdPrefix}-traceback`}>
            {traceback}
          </pre>
        </>
      ) : (
        <pre class="ht-text-mono ht-text-danger" data-testid={`${testIdPrefix}-traceback`}>
          {traceback}
        </pre>
      )}
    </div>
  );
}
