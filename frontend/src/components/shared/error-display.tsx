import type { components } from "@/api/generated-types";
import { cn } from "@/lib/utils";
import { formatDuration } from "@/utils/format";
import { executionStatusKind, STATUS_TONE_CLASSES } from "@/utils/status";

import { FIELD_LABEL_CLASS } from "./field-label";

type ExecutionStatus = components["schemas"]["ExecutionStatus"];

interface Props {
  status: ExecutionStatus;
  durationMs: number;
  errorType?: string | null;
  errorMessage?: string | null;
}

interface ResultDisplay {
  label: string;
  toneClass: string;
  message: string;
}

export function resolveResultDisplay(
  status: ExecutionStatus,
  durationMs: number,
  errorType?: string | null,
  errorMessage?: string | null,
): ResultDisplay {
  const toneClass = STATUS_TONE_CLASSES[executionStatusKind(status)];
  switch (status) {
    case "timed_out":
      return { label: "timeout", toneClass, message: `exceeded ${formatDuration(durationMs)} budget` };
    case "cancelled":
      return { label: "result", toneClass, message: `cancelled after ${formatDuration(durationMs)}` };
    case "error":
      return {
        label: "result",
        toneClass,
        message: errorMessage
          ? `${errorType ?? "Error"}: ${errorMessage}`
          : `completed in ${formatDuration(durationMs)}`,
      };
    case "skipped":
      return { label: "result", toneClass, message: "skipped" };
    case "success":
      return { label: "result", toneClass, message: `completed in ${formatDuration(durationMs)}` };
  }
}

export function ErrorDisplay({ status, durationMs, errorType, errorMessage }: Props) {
  const { label, toneClass, message } = resolveResultDisplay(status, durationMs, errorType, errorMessage);

  return (
    <div className="mb-2 flex items-baseline gap-2">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <span className={cn("font-mono text-xs", toneClass)}>{message}</span>
    </div>
  );
}
