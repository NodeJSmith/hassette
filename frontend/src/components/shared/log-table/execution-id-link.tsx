import type { ReactNode } from "react";
import { Link } from "wouter";

import type { LogEntry } from "@/api/endpoints";
import { logEntryExecutionHref } from "@/utils/app-routes";

interface Props {
  entry: LogEntry;
  linkClassName?: string;
  mutedClassName?: string;
  title?: string;
  children: ReactNode;
}

export function ExecutionIdLink({ entry, linkClassName, mutedClassName, title, children }: Props) {
  const href = logEntryExecutionHref(entry);
  if (href) {
    return (
      <Link href={href} className={linkClassName} title={title}>
        {children}
      </Link>
    );
  }
  if (mutedClassName) {
    return (
      <span className={mutedClassName} title={title}>
        {children}
      </span>
    );
  }
  return <>{children}</>;
}
