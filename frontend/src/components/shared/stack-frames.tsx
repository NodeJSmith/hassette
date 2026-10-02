import { useState } from "react";

import { Button } from "@/components/ui/button";

import type { StackFrame } from "../../api/endpoints";
import { TracebackLines } from "./traceback-viewer";

interface FrameRef {
  display_path: string;
  lineno: number;
  function: string;
}

/** `calendar_service.py:98 in get_calendar_events` — a frame's short summary form. */
export function frameLabel(frame: FrameRef): string {
  return `${frame.display_path}:${frame.lineno} in ${frame.function}`;
}

/**
 * Captured frames arrive innermost first; render them the way Python prints a traceback
 * (most recent call last) so the reading order matches every other stack in the UI.
 */
function framesAsTraceback(frames: StackFrame[]): string {
  return [...frames]
    .reverse()
    .map((f) => `  File "${f.filename}", line ${f.lineno}, in ${f.function}`)
    .join("\n");
}

interface Props {
  frames: StackFrame[];
  testId: string;
}

/** A "show stack" disclosure over a captured stack, absolute paths verbatim. */
export function StackDisclosure({ frames, testId }: Props) {
  const [open, setOpen] = useState(false);
  if (frames.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="ghost"
        size="xs"
        className="w-fit px-0 text-primary"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid={`${testId}-toggle`}
      >
        {open ? "hide stack" : "show stack"}
      </Button>
      {open && (
        <pre
          className="overflow-x-auto rounded-sm bg-muted px-3 py-2 font-mono text-[length:var(--text-mono-sm)] leading-relaxed"
          data-testid={testId}
        >
          <TracebackLines traceback={framesAsTraceback(frames)} />
        </pre>
      )}
    </div>
  );
}
