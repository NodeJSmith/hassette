import type { ReactNode } from "react";
import { Link } from "wouter";

import { cn } from "@/lib/utils";

import { appDetailPath, type HandlerKind, handlerPath } from "../../utils/app-routes";

interface Props {
  appKey: string;
  instanceName?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  children?: ReactNode;
}

export function AppLink({ appKey, instanceName, handlerKind, handlerId, children }: Props) {
  const query = instanceName !== undefined ? { instance: instanceName } : undefined;
  const href =
    handlerKind !== undefined && handlerId !== undefined
      ? handlerPath(appKey, handlerKind, handlerId, query)
      : appDetailPath(appKey, undefined, query);

  return (
    <Link
      href={href}
      className={cn(
        "font-mono text-sm text-primary no-underline",
        "hover:text-[var(--primary-hover)] hover:underline hover:decoration-[var(--primary-hover)]",
      )}
    >
      {children ?? appKey}
    </Link>
  );
}
