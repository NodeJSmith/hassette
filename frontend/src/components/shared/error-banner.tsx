import { useState } from "react";

import { Button } from "@/components/ui/button";

import { AlertShell } from "./alert-shell";
import { TracebackLines } from "./traceback-viewer";

interface ErrorBannerProps {
  heading?: string;
  errorType?: string | null;
  errorMessage: string | null;
  traceback?: string | null;
  "data-testid"?: string;
}

export function ErrorBanner({
  heading = "Last Error",
  errorType,
  errorMessage,
  traceback,
  "data-testid": testId,
}: ErrorBannerProps) {
  const [traceExpanded, setTraceExpanded] = useState(false);

  return (
    <AlertShell tone="danger" data-testid={testId}>
      <span className="mb-1 block text-sm font-semibold text-destructive">
        {heading}
        {errorType ? ` — ${errorType}` : ""}
      </span>
      {errorMessage && (
        <p className="break-all font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
          {errorMessage}
        </p>
      )}
      {traceback && (
        <div data-testid="traceback-content">
          <Button
            variant="link-muted"
            size="inline"
            className="mt-2 font-mono text-[length:var(--text-mono-sm)] text-destructive hover:text-destructive"
            data-testid="traceback-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((v) => !v)}
          >
            {traceExpanded ? "hide traceback" : "show traceback"}
          </Button>
          {traceExpanded && (
            <pre className="mt-2 overflow-x-auto whitespace-pre rounded-sm bg-muted px-3 py-2 font-mono text-xs leading-[var(--text-relaxed-leading)] text-foreground">
              <TracebackLines traceback={traceback} />
            </pre>
          )}
        </div>
      )}
    </AlertShell>
  );
}
