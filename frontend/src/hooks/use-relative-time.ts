import { useAppStore } from "../state/store";
import { formatRelativeTime } from "../utils/format";

export function useRelativeTime(timestamp: number | null): string {
  // Selecting tick subscribes this component to re-render on every tick increment,
  // which is exactly what forces the relative-time string to recompute periodically.
  useAppStore((s) => s.tick);
  if (timestamp === null) return "";
  return formatRelativeTime(timestamp);
}
