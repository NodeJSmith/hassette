import { AlertShell } from "../shared/alert-shell";
import { DropCounterRow } from "./drop-counter-row";
import { Panel, PANEL_BANNER_CLASS } from "./panel";

interface LoggingPanelProps {
  logQueueDrops: number;
  dbWriteQueueDrops: number;
  logPersistenceInactive: boolean;
}

/** Log records drop at one of two independent queues; each row names the bound to raise. */
export function LoggingPanel({ logQueueDrops, dbWriteQueueDrops, logPersistenceInactive }: LoggingPanelProps) {
  return (
    <Panel title="logging health" ariaLabel="Logging health" data-testid="diag-logging-panel">
      {logPersistenceInactive && (
        <AlertShell
          tone="warning"
          className={PANEL_BANNER_CLASS}
          role="alert"
          data-testid="diag-log-persistence-inactive"
        >
          Log persistence inactive — log records are not being written to the database, so the DB write drop count below
          has stopped moving.
        </AlertShell>
      )}
      <ul className="flex list-none flex-col p-0" aria-label="Log drop counters">
        <DropCounterRow label="Log queue full" value={logQueueDrops} testId="diag-drop-log-queue" />
        <DropCounterRow
          label="DB write queue full/unavailable"
          value={dbWriteQueueDrops}
          testId="diag-drop-db-write-queue"
        />
      </ul>
    </Panel>
  );
}
