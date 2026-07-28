import { cn } from "@/lib/utils";

import { formatDuration } from "../../utils/format";

interface Props {
  status: string;
  durationMs: number;
  errorType?: string | null;
  errorMessage?: string | null;
}

interface ResultDisplay {
  label: string;
  toneClass?: string;
  message: string;
}

function resolveResultDisplay(
  status: string,
  durationMs: number,
  errorType?: string | null,
  errorMessage?: string | null,
): ResultDisplay {
  if (status === "timed_out") {
    return {
      label: "timeout",
      toneClass: "text-[var(--status-warning)]",
      message: `exceeded ${formatDuration(durationMs)} budget`,
    };
  }

  if (status === "cancelled") {
    return {
      label: "result",
      toneClass: "text-[var(--status-cancel)]",
      message: `cancelled after ${formatDuration(durationMs)}`,
    };
  }

  if (status === "error" && errorMessage) {
    return { label: "result", toneClass: "text-destructive", message: `${errorType ?? "Error"}: ${errorMessage}` };
  }

  return { label: "result", message: `completed in ${formatDuration(durationMs)}` };
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
