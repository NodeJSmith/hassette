import { useAppState } from "../state/context";
import { formatRelativeTime } from "../utils/format";
import { useSubscribe } from "./use-subscribe";

export function useRelativeTime(timestamp: number | null): string {
  const { tick } = useAppState();
  useSubscribe(timestamp !== null ? tick : null);
  if (timestamp === null) return "";
  return formatRelativeTime(timestamp);
}
