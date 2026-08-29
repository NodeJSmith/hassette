import { useState } from "react";

import { cn } from "@/lib/utils";

import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import type { MergedService } from "./merge-services";

/** Both ServiceRow and its ServiceRowMeta child take exactly the merged service and nothing else. */
interface ServiceRowProps {
  service: MergedService;
}

/** Status, ready-phase, and retry annotations — a plainly running service shows none of them. */
function ServiceRowMeta({ service }: ServiceRowProps) {
  const retryAtLabel = useRelativeTime(service.retry_at);
  const isRunning = service.status === "running";
  const isCooling = service.status === "exhausted_cooling";

  return (
    <>
      {!isRunning && (
        <span
          className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary"
          data-testid={`diag-service-status-${service.resource_name}`}
        >
          {service.status}
        </span>
      )}
      {!isRunning && service.ready_phase && (
        <span
          className="text-sm italic text-muted-foreground"
          data-testid={`diag-service-phase-${service.resource_name}`}
        >
          {service.ready_phase}
        </span>
      )}
      {isCooling && service.retry_at !== null && (
        <span
          className="font-mono text-[length:var(--text-mono-sm)] text-[var(--status-warning)]"
          data-testid={`diag-service-retry-${service.resource_name}`}
        >
          retry {retryAtLabel}
        </span>
      )}
    </>
  );
}

export function ServiceRow({ service }: ServiceRowProps) {
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const isRunning = service.status === "running";
  // Rows with extra content (status text, phase, exception toggle) span the full grid width.
  const spansFullRow = !isRunning || !!service.exception;

  return (
    <li
      className={cn("min-w-0 py-1", spansFullRow && "col-[1/-1]")}
      data-testid={`diag-service-row-${service.resource_name}`}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <StatusShape kind={statusToKind(service.status)} size={STATUS_DOT_SIZE} />
        <span className="overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[length:var(--text-mono-sm)] font-medium text-foreground">
          {service.resource_name}
        </span>
        <ServiceRowMeta service={service} />
        {service.exception && (
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent p-0 font-inherit text-sm text-muted-foreground underline hover:text-foreground-secondary"
            aria-expanded={exceptionOpen}
            onClick={() => setExceptionOpen((v) => !v)}
          >
            {exceptionOpen ? "hide exception" : "show exception"}
          </button>
        )}
      </div>
      {exceptionOpen && service.exception && (
        <pre className="mt-2 whitespace-pre-wrap break-all rounded-sm bg-muted p-3 font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
          {service.exception}
        </pre>
      )}
    </li>
  );
}
