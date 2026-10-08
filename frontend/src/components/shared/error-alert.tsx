import type { ReactNode } from "react";

import { AlertShell } from "./alert-shell";

interface ErrorAlertProps {
  children: ReactNode;
  "data-testid"?: string;
}

/**
 * Single-message error alert for a failed page load or form submission.
 *
 * Use `ErrorBanner` instead when the error carries a heading, type, or traceback. The bottom margin
 * is dropped because every call site sits in a flex/gap layout that already spaces it.
 */
export function ErrorAlert({ children, "data-testid": testId }: ErrorAlertProps) {
  return (
    <AlertShell tone="danger" role="alert" className="mb-0 text-sm text-foreground" data-testid={testId}>
      {children}
    </AlertShell>
  );
}
