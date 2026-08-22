import { cn } from "@/lib/utils";

import type { components } from "../../api/generated-types";
import { formatDuration } from "../../utils/format";

type ExecutionStatus = components["schemas"]["ExecutionStatus"];

interface Props {
  status: ExecutionStatus;
  durationMs: number;
  errorType?: string | null;
  errorMessage?: string | null;
}

interface ResultDisplay {
  label: string;
  toneClass?: string;
  message: string;
}

export function resolveResultDisplay(
  status: ExecutionStatus,
  durationMs: number,
  errorType?: string | null,
  errorMessage?: string | null,
): ResultDisplay {
  switch (status) {
    case "timed_out":
      return {
        label: "timeout",
        toneClass: "text-[var(--status-warning)]",
        message: `exceeded ${formatDuration(durationMs)} budget`,
      };
    case "cancelled":
      return {
        label: "result",
        toneClass: "text-[var(--status-cancel)]",
        message: `cancelled after ${formatDuration(durationMs)}`,
      };
    case "error":
      return {
        label: "result",
        toneClass: "text-destructive",
        message: errorMessage
          ? `${errorType ?? "Error"}: ${errorMessage}`
          : `completed in ${formatDuration(durationMs)}`,
      };
    case "skipped":
      return { label: "result", toneClass: "text-muted-foreground", message: "skipped" };
    case "success":
      return { label: "result", message: `completed in ${formatDuration(durationMs)}` };
  }
}

export function ErrorDisplay({ status, durationMs, errorType, errorMessage }: Props) {
  const { label, toneClass, message } = resolveResultDisplay(status, durationMs, errorType, errorMessage);

  return (
    <div className="mb-2 flex items-baseline gap-2">
      <span className="mr-2 font-mono text-xs uppercase tracking-[var(--text-label-tracking)] text-foreground-faint">
        {label}
      </span>
      <span className={cn("font-mono text-xs", toneClass)}>{message}</span>
    </div>
  );
}
