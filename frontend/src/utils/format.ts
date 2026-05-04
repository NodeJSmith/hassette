/** Format a Unix timestamp as "MM/DD HH:MM:SS AM/PM" to match old UI. */
export function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000);
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
  if (secs < 60) return `${secs}s`;
  const parts: string[] = [];
  const days = Math.floor(secs / 86400);
  if (days > 0) { parts.push(`${days}d`); secs %= 86400; }
  const hours = Math.floor(secs / 3600);
  if (hours > 0) { parts.push(`${hours}h`); secs %= 3600; }
  const mins = Math.floor(secs / 60);
  if (mins > 0) { parts.push(`${mins}m`); secs %= 60; }
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
  const n = parseInt(sourceLocation.slice(colonIdx + 1), 10);
  return { filename, line: Number.isFinite(n) ? n : null };
}

/** Format a Unix timestamp as a relative time string (e.g., "2m ago"). */
export function formatRelativeTime(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/** Format a Unix timestamp as a compact age string (e.g., "12s", "3m", "1h", "2d"). */
export function formatAge(ts: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - ts);
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}
