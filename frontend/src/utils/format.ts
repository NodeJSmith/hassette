export const MS_PER_SECOND = 1000;
export const SECONDS_PER_MINUTE = 60;
export const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;

/** Format a Unix timestamp as "MM/DD HH:MM:SS AM/PM" to match old UI. */
export function formatTimestamp(ts: number): string {
  const d = new Date(ts * MS_PER_SECOND);
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true });
  return `${month}/${day} ${time}`;
}

/** Format a duration in milliseconds with one decimal (e.g., "158.0ms"). */
export function formatDuration(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Format a duration or "—" if null/undefined/zero. Use for averages where 0 means "no data". */
export function formatDurationOrDash(ms: number | null | undefined): string {
  return ms !== null && ms !== undefined && ms > 0 ? formatDuration(ms) : "—";
}

/** Format a duration or "—" if null/undefined. Use for min/max where 0 is a valid value. */
export function formatOptionalDuration(ms: number | null | undefined): string {
  return ms !== null && ms !== undefined ? formatDuration(ms) : "—";
}

/** Pluralize a label based on count (e.g., pluralize(1, "entry", "entries") → "1 entry"). */
export function pluralize(count: number, singular: string, plural?: string): string {
  const label = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${count} ${label}`;
}

/**
 * Format a trigger detail duration string (e.g., "432000s") as human-readable.
 * Passes through non-seconds strings unchanged (e.g., "30 7 * * 1-5", "07:00").
 */
export function formatTriggerDetail(detail: string): string {
  const match = detail.match(/^(\d+)s$/);
  if (!match) return detail;
  let secs = parseInt(match[1], 10);
  if (secs < SECONDS_PER_MINUTE) return `${secs}s`;
  const parts: string[] = [];
  const days = Math.floor(secs / SECONDS_PER_DAY);
  if (days > 0) {
    parts.push(`${days}d`);
    secs %= SECONDS_PER_DAY;
  }
  const hours = Math.floor(secs / SECONDS_PER_HOUR);
  if (hours > 0) {
    parts.push(`${hours}h`);
    secs %= SECONDS_PER_HOUR;
  }
  const mins = Math.floor(secs / SECONDS_PER_MINUTE);
  if (mins > 0) {
    parts.push(`${mins}m`);
    secs %= SECONDS_PER_MINUTE;
  }
  if (secs > 0) parts.push(`${secs}s`);
  return parts.join(" ");
}

/** Truncate a UUID or ID string to 8 chars with ellipsis, or "—" for null/undefined. */
export function truncateId(id: string | null | undefined): string {
  if (!id) return "—";
  if (id.length <= 8) return id;
  return id.slice(0, 8) + "…";
}

/** Parse source_location "filename.py:LINE" into { filename, line }. */
export function parseSourceLocation(sourceLocation: string): { filename: string; line: number | null } {
  const colonIdx = sourceLocation.lastIndexOf(":");
  if (colonIdx <= 0) return { filename: sourceLocation, line: null };
  const filename = sourceLocation.slice(0, colonIdx);
  const lineNum = parseInt(sourceLocation.slice(colonIdx + 1), 10);
  return { filename, line: Number.isFinite(lineNum) ? lineNum : null };
}

/** Format a Unix timestamp as a relative time string (e.g., "2m ago", "in 8m"). */
export function formatRelativeTime(ts: number): string {
  const now = Date.now() / MS_PER_SECOND;
  const diff = now - ts;
  if (diff < 0) {
    const abs = -diff;
    if (abs < SECONDS_PER_MINUTE) return "in <1m";
    if (abs < SECONDS_PER_HOUR) return `in ${Math.floor(abs / SECONDS_PER_MINUTE)}m`;
    if (abs < SECONDS_PER_DAY) return `in ${Math.floor(abs / SECONDS_PER_HOUR)}h`;
    return `in ${Math.floor(abs / SECONDS_PER_DAY)}d`;
  }
  if (diff < SECONDS_PER_MINUTE) return "just now";
  if (diff < SECONDS_PER_HOUR) return `${Math.floor(diff / SECONDS_PER_MINUTE)}m ago`;
  if (diff < SECONDS_PER_DAY) return `${Math.floor(diff / SECONDS_PER_HOUR)}h ago`;
  return `${Math.floor(diff / SECONDS_PER_DAY)}d ago`;
}

/** Canonical display labels for time presets. */
export const TIME_PRESET_LABELS: Record<string, string> = {
  "since-restart": "since restart",
  "1h": "in last hour",
  "24h": "in last 24h",
  "7d": "in last 7 days",
};

/** Format a Unix timestamp as a compact age string (e.g., "12s", "3m", "1h", "2d"). */
export function formatAge(ts: number): string {
  const now = Date.now() / MS_PER_SECOND;
  const diff = Math.max(0, now - ts);
  if (diff < SECONDS_PER_MINUTE) return `${Math.floor(diff)}s`;
  if (diff < SECONDS_PER_HOUR) return `${Math.floor(diff / SECONDS_PER_MINUTE)}m`;
  if (diff < SECONDS_PER_DAY) return `${Math.floor(diff / SECONDS_PER_HOUR)}h`;
  return `${Math.floor(diff / SECONDS_PER_DAY)}d`;
}

/** Extract the last segment after the final dot (e.g. "foo.bar.Baz" → "Baz"). */
export function lastDotSegment(s: string): string {
  const idx = s.lastIndexOf(".");
  return idx === -1 ? s : s.slice(idx + 1);
}

/** Format a failure rate as a percentage string (e.g., "3.0%"), or "—" if total is 0. */
export function formatRate(failed: number, total: number): string {
  return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
}

export function formatUptime(seconds: number): string {
  if (seconds < SECONDS_PER_MINUTE) return `${Math.floor(seconds)}s`;
  if (seconds < SECONDS_PER_HOUR) return `${Math.floor(seconds / SECONDS_PER_MINUTE)}m`;
  if (seconds < SECONDS_PER_DAY)
    return `${Math.floor(seconds / SECONDS_PER_HOUR)}h ${Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE)}m`;
  return `${Math.floor(seconds / SECONDS_PER_DAY)}d ${Math.floor((seconds % SECONDS_PER_DAY) / SECONDS_PER_HOUR)}h`;
}
