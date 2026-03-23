interface FailedApp {
  app_key: string;
  error_message: string | null;
}

interface Props {
  failedApps: FailedApp[];
}

export function AlertBanner({ failedApps }: Props) {
  if (failedApps.length === 0) return null;

  return (
    <div class="ht-alert ht-alert--danger">
      <strong>{failedApps.length} app{failedApps.length > 1 ? "s" : ""} failed</strong>
      <ul class="ht-alert-list">
        {failedApps.map((app) => (
          <li key={app.app_key}>
            <a href={`/apps/${app.app_key}`}>{app.app_key}</a>
            {app.error_message && (
              <span class="ht-text-secondary"> — {app.error_message}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
