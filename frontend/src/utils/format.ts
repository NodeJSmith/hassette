/** Format a Unix timestamp as a locale-appropriate time string. */
export function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

/** Format a duration in milliseconds as a human-readable string. */
export function formatDuration(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
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
