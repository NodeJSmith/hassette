import { Link } from "wouter";

import type { LogEntry } from "@/api/endpoints";
import { logEntryExecutionHref } from "@/utils/app-routes";

interface Props {
  entry: LogEntry;
  linkClassName?: string;
  mutedClassName?: string;
  title?: string;
  children: preact.ComponentChildren;
}

export function ExecutionIdLink({ entry, linkClassName, mutedClassName, title, children }: Props) {
  const href = logEntryExecutionHref(entry);
  if (href) {
    return (
      <Link href={href} class={linkClassName} title={title}>
        {children}
      </Link>
    );
  }
  if (mutedClassName) {
    return (
      <span class={mutedClassName} title={title}>
        {children}
      </span>
    );
  }
  return <>{children}</>;
}
