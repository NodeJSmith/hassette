import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Semantic tone of a banner — selects the destructive or warning token pair. */
export type AlertTone = "danger" | "warning";

const TONE_CLASSES: Record<AlertTone, string> = {
  danger: "border-[color:color-mix(in_srgb,var(--destructive)_30%,transparent)] bg-[var(--destructive-bg)]",
  warning: "border-[var(--status-warning)] bg-[var(--status-warning-bg)]",
};

interface AlertBannerProps {
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
 * Owns the container geometry so tone variants can't drift apart; callers supply content.
 */
export function AlertBanner({ tone, children, className, role, "data-testid": testId }: AlertBannerProps) {
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
