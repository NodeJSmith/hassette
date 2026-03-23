import { useAppState } from "../state/context";
import { formatRelativeTime } from "../utils/format";

export function useRelativeTime(timestamp: number | null): string {
  const { tick } = useAppState();
  void tick.value; // subscribe to periodic updates
  if (timestamp === null) return "";
  return formatRelativeTime(timestamp);
}
