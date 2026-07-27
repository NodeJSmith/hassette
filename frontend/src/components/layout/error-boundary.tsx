import type { ReactNode } from "react";
import { ErrorBoundary as ReactErrorBoundary, type FallbackProps } from "react-error-boundary";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface Props {
  children: ReactNode;
  resetKey?: string;
}

function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <Card variant="error" role="alert" data-testid="error-card">
      <h2>Something went wrong</h2>
      <p className="ht-text-secondary">{message}</p>
      <Button variant="default" onClick={resetErrorBoundary}>
        Retry
      </Button>
    </Card>
  );
}

export function ErrorBoundary({ children, resetKey }: Props) {
  return (
    <ReactErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[resetKey]}>
      {children}
    </ReactErrorBoundary>
  );
}
