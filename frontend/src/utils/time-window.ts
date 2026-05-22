import type { TimePreset } from "../state/create-app-state";
import { MS_PER_SECOND } from "./format";

/** Window sizes in seconds for the fixed-window presets. */
export const PRESET_WINDOW_SECONDS: Record<Exclude<TimePreset, "since-restart">, number> = {
  "1h": 3600,
  "24h": 86400,
  "7d": 604800,
};

/**
 * Compute the `since` timestamp (Unix epoch seconds) for the given preset.
 *
 * Returns undefined only for "since-restart" when uptimeSeconds is null
 * (WS connected message not yet received). Fixed-window presets (1h, 24h, 7d)
 * are independent of uptime and never block.
 */
export function resolveSince(preset: TimePreset, uptimeSeconds: number | null): number | undefined {
  if (preset === "since-restart") {
    if (uptimeSeconds === null) return undefined;
    return Date.now() / MS_PER_SECOND - uptimeSeconds;
  }

  return Date.now() / MS_PER_SECOND - PRESET_WINDOW_SECONDS[preset];
}
