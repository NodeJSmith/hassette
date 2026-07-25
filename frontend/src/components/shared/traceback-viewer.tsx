import clsx from "clsx";
import type { JSX } from "preact";

import styles from "./detail-panel.module.css";
import tb from "./traceback-viewer.module.css";

/** `  File "/app/x.py", line 42, in handler` — the only structured line in a traceback. */
const FRAME_RE = /^(\s*)File "(.*)", line (\d+), in (.*)$/;

function splitTraceback(traceback: string): { frames: string; errorLine: string } | null {
  const trimmed = traceback.trimEnd();
  const lastNewline = trimmed.lastIndexOf("\n");
  if (lastNewline <= 0) return null;
  return { frames: trimmed.slice(0, lastNewline), errorLine: trimmed.slice(lastNewline + 1) };
}

/**
 * Colour one traceback line by its role.
 *
 * Rendered as JSX rather than injected HTML — traceback text originates in
 * exception messages, so it must never be interpreted as markup.
 */
function renderLine(line: string, key: number): JSX.Element {
  const frame = FRAME_RE.exec(line);
  if (frame) {
    const [, indent, path, lineNo, func] = frame;
    return (
      <span key={key} class={tb.line}>
        {indent}
        <span class={tb.frameKeyword}>File </span>
        <span class={tb.path}>"{path}"</span>
        <span class={tb.frameKeyword}>, line </span>
        <span class={tb.lineNo}>{lineNo}</span>
        <span class={tb.frameKeyword}>, in </span>
        <span class={tb.func}>{func}</span>
      </span>
    );
  }

  if (line.startsWith("Traceback")) {
    return (
      <span key={key} class={clsx(tb.line, tb.header)}>
        {line}
      </span>
    );
  }

  // Everything else is the echoed source line under a frame.
  return (
    <span key={key} class={clsx(tb.line, tb.sourceLine)}>
      {line}
    </span>
  );
}

/** The coloured lines on their own, for callers that supply their own framing. */
export function TracebackLines({ traceback }: { traceback: string }) {
  return <>{traceback.trimEnd().split("\n").map(renderLine)}</>;
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
            {split.frames.split("\n").map(renderLine)}
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
