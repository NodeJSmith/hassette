import type { ComponentChildren } from "preact";
import { useEffect, useErrorBoundary, useRef } from "preact/hooks";
import { Card } from "../shared/card";
import { Button } from "../shared/button";

interface Props {
  children: ComponentChildren;
  resetKey?: string;
}

export function ErrorBoundary({ children, resetKey }: Props) {
  const [error, resetError] = useErrorBoundary();

  // Stabilise resetError in a ref so the effect's dependency is only resetKey,
  // not the new function identity that useErrorBoundary creates on every render.
  // Without this, the effect fires after every render, immediately resetting
  // the caught error before the fallback UI can display.
  const resetErrorRef = useRef(resetError);
  resetErrorRef.current = resetError;

  useEffect(() => {
    if (error) resetErrorRef.current();
  }, [resetKey]); // intentionally omits resetErrorRef — it's a stable ref, not a dep

  if (error) {
    return (
      <Card variant="error" data-testid="error-card">
        <h2>Something went wrong</h2>
        <p class="ht-text-secondary">{error instanceof Error ? error.message : String(error)}</p>
        <Button variant="primary" onClick={resetError}>
          Retry
        </Button>
      </Card>
    );
  }
  return <>{children}</>;
}
