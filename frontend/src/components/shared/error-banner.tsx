import { useState } from "preact/hooks";

interface Props {
  heading?: string;
  errorType?: string | null;
  errorMessage: string | null;
  traceback?: string | null;
  "data-testid"?: string;
}

export function ErrorBanner({ heading = "Last Error", errorType, errorMessage, traceback, "data-testid": testId }: Props) {
  const [traceExpanded, setTraceExpanded] = useState(false);

  return (
    <div class="ht-error-banner" data-testid={testId}>
      <span class="ht-error-banner__heading">
        {heading}{errorType ? ` — ${errorType}` : ""}
      </span>
      {errorMessage && (
        <p class="ht-error-banner__message">{errorMessage}</p>
      )}
      {traceback && (
        <div data-testid="traceback-content">
          <button
            type="button"
            class="ht-error-banner__traceback-toggle"
            data-testid="traceback-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((v) => !v)}
          >
            {traceExpanded ? "hide traceback" : "show traceback"}
          </button>
          {traceExpanded && (
            <pre class="ht-traceback">{traceback}</pre>
          )}
        </div>
      )}
    </div>
  );
}
