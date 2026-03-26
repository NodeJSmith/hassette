import type { ComponentChildren } from "preact";
import { useEffect, useErrorBoundary } from "preact/hooks";

interface Props {
  children: ComponentChildren;
  resetKey?: string;
}

export function ErrorBoundary({ children, resetKey }: Props) {
  const [error, resetError] = useErrorBoundary();

  useEffect(() => {
    if (error) resetError();
  }, [resetKey, resetError]);

  if (error) {
    return (
      <div class="ht-card ht-error-card">
        <h2>Something went wrong</h2>
        <p class="ht-text-secondary">{error instanceof Error ? error.message : String(error)}</p>
        <button
          class="ht-btn ht-btn--primary"
          onClick={resetError}
        >
          Retry
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
