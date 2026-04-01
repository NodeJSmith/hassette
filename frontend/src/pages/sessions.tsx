import { useEffect } from "preact/hooks";
import { getSessionList, type SessionListEntry } from "../api/endpoints";
import { IconHistory } from "../components/shared/icons";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { formatTimestamp } from "../utils/format";
import type { StatusVariant } from "../utils/status";

const SESSION_STATUS_MAP: ReadonlyMap<string, StatusVariant> = new Map([
  ["running", "success"],
  ["success", "success"],
  ["failure", "danger"],
  ["unknown", "neutral"],
]);

function sessionStatusToVariant(status: string): StatusVariant {
  return SESSION_STATUS_MAP.get(status) ?? "neutral";
}

function formatSessionDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function SessionRow({ session }: { session: SessionListEntry }) {
  const variant = sessionStatusToVariant(session.status);
  return (
    <tr>
      <td>
        <span class={`ht-badge ht-badge--sm ht-badge--${variant}`}>
          {session.status}
        </span>
      </td>
      <td>{formatTimestamp(session.started_at)}</td>
      <td>{session.stopped_at !== null ? formatTimestamp(session.stopped_at) : "-"}</td>
      <td>{formatSessionDuration(session.duration_seconds)}</td>
      <td>{session.error_type ?? "-"}</td>
      <td class="ht-text-truncate">{session.error_message ?? "-"}</td>
    </tr>
  );
}

export function SessionsPage() {
  useEffect(() => { document.title = "Sessions - Hassette"; }, []);

  const sessions = useApi(getSessionList);

  if (sessions.loading.value) {
    return <Spinner />;
  }

  return (
    <div>
      <h1 class="ht-heading-4 ht-mb-4">
        <IconHistory />
        <span>Sessions</span>
      </h1>
      {sessions.error.value && (
        <p class="ht-text-danger">Failed to load sessions: {sessions.error.value}</p>
      )}
      <div class="ht-card">
        <div class="ht-table-wrap">
          <table class="ht-table" data-testid="sessions-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Started At</th>
                <th>Stopped At</th>
                <th>Duration</th>
                <th>Error Type</th>
                <th>Error Message</th>
              </tr>
            </thead>
            <tbody>
              {sessions.data.value && sessions.data.value.length > 0 ? (
                sessions.data.value.map((session) => (
                  <SessionRow key={session.id} session={session} />
                ))
              ) : (
                <tr>
                  <td colSpan={6} class="ht-text-muted ht-text-center">
                    No sessions recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
