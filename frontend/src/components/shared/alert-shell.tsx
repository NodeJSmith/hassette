import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Semantic tone of a banner — selects the destructive or warning token pair. */
export type AlertTone = "danger" | "warning";

// The two tones intentionally differ in border treatment: `danger` uses `--destructive-border`
// (global.css aliases it to `--err-border`, which is `--err` at 30% alpha) so a full-width error
// block doesn't read as a hard red rule, while `warning` uses `--status-warning` at full
// strength. Both are carried over verbatim from the call sites this shell replaced — a new tone
// should pick whichever reads better, not copy either by default.
const TONE_CLASSES: Record<AlertTone, string> = {
  danger: "border-[var(--destructive-border)] bg-[var(--destructive-bg)]",
  warning: "border-[var(--status-warning)] bg-[var(--status-warning-bg)]",
};

interface AlertShellProps {
  tone: AlertTone;
  children: ReactNode;
  /** Extra classes for content-level styling (text color, size); the shell is fixed. */
  className?: string;
  role?: string;
  "data-testid"?: string;
}

/**
 * Shared shell for full-width inline banners (errors, blocked apps).
 *
 * Distinct from `components/layout/alert-banner.tsx`'s `AlertBanner`, which is a specific
 * failed-apps notice rather than a reusable container.
 *
 * Owns the container geometry so tone variants can't drift apart; callers supply content.
 */
export function AlertShell({ tone, children, className, role, "data-testid": testId }: AlertShellProps) {
  return (
    <div
      className={cn("mb-4 rounded-md border px-4 py-3", TONE_CLASSES[tone], className)}
      role={role}
      data-testid={testId}
    >
      {children}
    </div>
  );
}
