import { useEffect } from "preact/hooks";
import { getSessionList, type SessionListEntry } from "../api/endpoints";
import { IconHistory } from "../components/shared/icons";
import { Spinner } from "../components/shared/spinner";
import { StatusBadge } from "../components/shared/status-badge";
import { useApi } from "../hooks/use-api";
import { formatTimestamp } from "../utils/format";

function formatSessionDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  const totalSeconds = Math.round(seconds);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  if (totalSeconds < 3600) return remainingSeconds > 0 ? `${totalMinutes}m ${remainingSeconds}s` : `${totalMinutes}m`;
  const hours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes % 60;
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function SessionRow({ session }: { session: SessionListEntry }) {
  return (
    <tr>
      <td>
        <StatusBadge status={session.status} size="small" />
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
