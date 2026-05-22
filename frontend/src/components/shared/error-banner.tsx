import { useState } from "preact/hooks";

import styles from "./error-banner.module.css";

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
    <div class={styles.banner} data-testid={testId}>
      <span class={styles.heading}>
        {heading}
        {errorType ? ` — ${errorType}` : ""}
      </span>
      {errorMessage && <p class={styles.message}>{errorMessage}</p>}
      {traceback && (
        <div data-testid="traceback-content">
          <button
            type="button"
            class={styles.tracebackToggle}
            data-testid="traceback-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((v) => !v)}
          >
            {traceExpanded ? "hide traceback" : "show traceback"}
          </button>
          {traceExpanded && <pre class="ht-traceback">{traceback}</pre>}
        </div>
      )}
    </div>
  );
}
