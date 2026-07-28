import type { ReactNode } from "react";

interface Props {
  testId: string;
  children: ReactNode;
}

export function HandlerDetailLayout({ testId, children }: Props) {
  return (
    <div className="flex flex-col gap-4" data-testid={testId}>
      <div className="rounded-md border border-border bg-card p-4">{children}</div>
    </div>
  );
}
