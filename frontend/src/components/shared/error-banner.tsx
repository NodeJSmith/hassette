import { useState } from "react";

import styles from "./error-banner.module.css";
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
    <div className={styles.banner} data-testid={testId}>
      <span className={styles.heading}>
        {heading}
        {errorType ? ` — ${errorType}` : ""}
      </span>
      {errorMessage && <p className={styles.message}>{errorMessage}</p>}
      {traceback && (
        <div data-testid="traceback-content">
          <button
            type="button"
            className={styles.tracebackToggle}
            data-testid="traceback-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((v) => !v)}
          >
            {traceExpanded ? "hide traceback" : "show traceback"}
          </button>
          {traceExpanded && (
            <pre className="ht-traceback">
              <TracebackLines traceback={traceback} />
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
