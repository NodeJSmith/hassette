import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  "data-testid"?: string;
  children?: ReactNode;
}

export function EmptyState({ icon = "∅", title, body, "data-testid": testId, children }: EmptyStateProps) {
  return (
    <div className="p-6 text-center" data-testid={testId}>
      {icon && <div className="mb-2 text-[length:var(--text-h1)] text-foreground-faint">{icon}</div>}
      <div className="mb-1 text-sm font-medium text-foreground-secondary">{title}</div>
      {body && <div className="mx-auto max-w-[var(--size-content-narrow)] text-xs text-muted-foreground">{body}</div>}
      {children}
    </div>
  );
}
