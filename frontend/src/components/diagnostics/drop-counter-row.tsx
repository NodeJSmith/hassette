import { cn } from "@/lib/utils";

interface DropCounterRowProps {
  label: string;
  value: number;
  testId: string;
}

/** One labelled drop counter; a non-zero count turns warning-toned. */
export function DropCounterRow({ label, value, testId }: DropCounterRowProps) {
  return (
    <li
      className="flex items-center gap-3 border-b border-[var(--border-subtle)] py-2 last:border-b-0"
      data-testid={testId}
    >
      <span className="flex-1 text-sm text-foreground-secondary">{label}</span>
      <span
        className={cn(
          "min-w-[3ch] text-right font-mono text-[length:var(--text-mono-md)] text-foreground-secondary",
          value > 0 && "text-[var(--status-warning)]",
        )}
      >
        {value}
      </span>
    </li>
  );
}
