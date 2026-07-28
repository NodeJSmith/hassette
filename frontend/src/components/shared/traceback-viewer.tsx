import type { JSX } from "react";

import { cn } from "@/lib/utils";

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
      <span key={key} className="block">
        {indent}
        <span className="text-muted-foreground">File </span>
        <span className="text-primary" data-traceback-token="path">
          "{path}"
        </span>
        <span className="text-muted-foreground">, line </span>
        <span className="text-[var(--status-warning)]" data-traceback-token="line-number">
          {lineNo}
        </span>
        <span className="text-muted-foreground">, in </span>
        <span className="text-[var(--handler-listener)]" data-traceback-token="function">
          {func}
        </span>
      </span>
    );
  }

  if (line.startsWith("Traceback")) {
    return (
      <span key={key} className="block text-muted-foreground">
        {line}
      </span>
    );
  }

  // Everything else is the echoed source line under a frame.
  return (
    <span key={key} className="block text-foreground">
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
    <div className="mt-3 border-t border-border pt-3">
      <span className="mb-2 block font-mono text-xs uppercase tracking-[var(--text-label-tracking)] text-foreground-faint">
        traceback
      </span>
      {split ? (
        <>
          <div className="mb-3 rounded-sm bg-[var(--destructive-bg)] px-3 py-2">
            <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[length:var(--text-mono-sm)] font-medium text-destructive">
              {split.errorLine}
            </pre>
          </div>
          <pre
            className="m-0 whitespace-pre-wrap break-words font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary"
            data-testid={`${testIdPrefix}-traceback`}
          >
            {split.frames.split("\n").map(renderLine)}
          </pre>
        </>
      ) : (
        <pre className={cn("font-mono text-destructive")} data-testid={`${testIdPrefix}-traceback`}>
          {traceback}
        </pre>
      )}
    </div>
  );
}
