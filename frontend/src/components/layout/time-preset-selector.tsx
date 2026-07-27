import { useEffect } from "react";

import { cn } from "@/lib/utils";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { useQueryParams } from "../../hooks/use-query-params";
import type { TimePreset } from "../../state/store";
import { isTimePreset, useAppStore } from "../../state/store";
import { formatUptime } from "../../utils/format";

const PRESETS: { value: TimePreset; label: string }[] = [
  { value: "since-restart", label: "Since restart" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function TimePresetSelector() {
  const timePreset = useAppStore((s) => s.timePreset);
  const setTimePreset = useAppStore((s) => s.setTimePreset);
  const uptimeSeconds = useAppStore((s) => s.uptimeSeconds);
  const setUrlWindowParam = useAppStore((s) => s.setUrlWindowParam);
  const qp = useQueryParams();
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  useEffect(() => {
    const windowParam = qp.get("window");
    if (windowParam !== null && isTimePreset(windowParam)) {
      setUrlWindowParam(windowParam);
    } else {
      setUrlWindowParam(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only; qp/setUrlWindowParam are stable
  }, []);

  const current = timePreset;
  const uptime = uptimeSeconds;
  const showUptime = uptime !== null && Number.isFinite(uptime);

  const handlePreset = (value: TimePreset) => {
    setTimePreset(value);
    setUrlWindowParam(value);
    qp.set({ window: value });
  };

  if (isMobile) {
    return (
      <div
        className="flex items-center gap-0 rounded-md border-0 bg-transparent max-[768px]:border-0 max-[768px]:bg-transparent"
        data-testid="time-preset-selector"
      >
        <select
          className="min-h-9 cursor-pointer appearance-auto border-none bg-popover px-2 py-1 text-xs font-medium text-foreground/90"
          value={current}
          onChange={(e) => handlePreset((e.target as HTMLSelectElement).value as TimePreset)}
          aria-label="Time window"
        >
          {PRESETS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {showUptime && <span className="px-2 font-mono text-xs text-[var(--ink-4)]">up {formatUptime(uptime)}</span>}
      </div>
    );
  }

  return (
    <div
      className="flex items-center gap-0 overflow-hidden rounded-md border bg-popover"
      data-testid="time-preset-selector"
    >
      {PRESETS.map(({ value, label }) => {
        const active = current === value;
        return (
          <button
            key={value}
            type="button"
            className={cn(
              "min-h-9 cursor-pointer border-0 border-r border-r-[var(--line-2)] bg-transparent px-2 py-0 text-xs leading-relaxed font-medium whitespace-nowrap text-muted-foreground transition-colors last:border-r-0",
              !active && "hover:bg-[var(--bg-active)] hover:text-foreground",
              active && "bg-[var(--accent-soft)] text-[var(--accent)]",
            )}
            aria-pressed={active}
            onClick={() => handlePreset(value)}
          >
            {label}
          </button>
        );
      })}
      {showUptime && (
        <span className="border-l border-l-[var(--line-2)] px-2 font-mono text-xs text-[var(--ink-4)]">
          up {formatUptime(uptime)}
        </span>
      )}
    </div>
  );
}
