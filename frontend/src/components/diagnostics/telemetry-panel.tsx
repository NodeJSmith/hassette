import { DropCounterRow } from "./drop-counter-row";
import { Panel, PANEL_WARNING_CLASS } from "./panel";

/** Telemetry drop counters and degradation flag, as carried on the WS stream. */
export interface TelemetryCounters {
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
  telemetryDegraded: boolean;
}

export function TelemetryPanel({
  droppedOverflow,
  droppedExhausted,
  droppedShutdown,
  errorHandlerFailures,
  telemetryDegraded,
}: TelemetryCounters) {
  return (
    <Panel title="telemetry health" ariaLabel="Telemetry health" data-testid="diag-telemetry-panel">
      {telemetryDegraded && (
        <div className={PANEL_WARNING_CLASS} role="alert" data-testid="diag-telemetry-degraded">
          Telemetry degraded — writes may be failing or the database is unavailable.
        </div>
      )}
      {droppedOverflow + droppedExhausted + droppedShutdown + errorHandlerFailures > 0 && (
        <ul className="flex list-none flex-col p-0" aria-label="Drop counters">
          <DropCounterRow label="Buffer overflow" value={droppedOverflow} testId="diag-drop-overflow" />
          <DropCounterRow label="Write failed" value={droppedExhausted} testId="diag-drop-exhausted" />
          <DropCounterRow label="During shutdown" value={droppedShutdown} testId="diag-drop-shutdown" />
          <DropCounterRow
            label="Error handler failures"
            value={errorHandlerFailures}
            testId="diag-drop-error-handler"
          />
        </ul>
      )}
    </Panel>
  );
}
