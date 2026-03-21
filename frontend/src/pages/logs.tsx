import { LogTable } from "../components/shared/log-table";

export function LogsPage() {
  return (
    <div>
      <h1>Logs</h1>
      <LogTable showAppColumn={true} />
    </div>
  );
}
