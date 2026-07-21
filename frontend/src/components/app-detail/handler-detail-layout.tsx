import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import type { HandlerKind } from "../../utils/app-routes";
import { parseSourceLocation } from "../../utils/format";
import { Badge } from "../shared/badge";
import { Button } from "../shared/button";
import { Chip, type ChipKind } from "../shared/chip";
import type { DetailStatsCell } from "../shared/detail-stats";
import { DetailStats } from "../shared/detail-stats";
import { ErrorBanner } from "../shared/error-banner";
import { type ExecutionRecord, ExecutionTable } from "../shared/execution-table";
import { RegistrationSource } from "../shared/registration-source";
import { SourceLocation } from "../shared/source-location";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import styles from "./handler-detail-layout.module.css";

interface ErrorInfo {
  type: string | null;
  message: string | null;
  traceback: string | null;
}

interface Props {
  testId: string;
  testIdPrefix: "handler" | "job";
  kindLabel: string;
  statusKind: ChipKind;
  name: string;
  subtitle?: string | null;
  registrationSource?: string | null;
  chips?: ComponentChildren;
  extras?: ComponentChildren;
  headerActions?: ComponentChildren;
  sourceLocation?: string | null;
  onViewCode?: (line?: number) => void;
  error?: ErrorInfo | null;
  statsCells: DetailStatsCell[];
  statsTestId: string;
  executionHeading: string;
  executionRecords: ExecutionRecord[];
  executionKind: "handler" | "job";
  executionTableId: string;
  executionLoading: boolean;
  executionHasData: boolean;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}

export function HandlerDetailLayout({
  testId,
  testIdPrefix,
  kindLabel,
  statusKind,
  name,
  subtitle,
  registrationSource,
  chips,
  extras,
  headerActions,
  sourceLocation,
  onViewCode,
  error,
  statsCells,
  statsTestId,
  executionHeading,
  executionRecords,
  executionKind,
  executionTableId,
  executionLoading,
  executionHasData,
  appKey,
  handlerKind,
  handlerId,
  instanceQs,
}: Props) {
  const [registrationExpanded, setRegistrationExpanded] = useState(false);
  const isFailing = statusKind === "err";
  const sourceLine = sourceLocation ? parseSourceLocation(sourceLocation).line : null;

  return (
    <div class={styles.wrapper} data-testid={testId}>
      <div class={styles.content}>
        <div class={styles.header}>
          <Chip variant="kind" kind={statusKind} aria-label={`kind: ${kindLabel}`}>
            <StatusShape kind={statusKind} size={8} />
            {kindLabel}
          </Chip>
          <span class={styles.handlerName}>{name}</span>
          {isFailing && (
            <Badge variant="danger" size="sm" data-testid="handler-status-pill">
              failing
            </Badge>
          )}
          {headerActions && <div class={styles.headerActions}>{headerActions}</div>}
        </div>

        {subtitle && (
          <p class={styles.subtitle} data-testid={`${testIdPrefix}-human-description`}>
            {subtitle}
          </p>
        )}

        {extras}

        {chips}

        {isFailing && error && (error.message || error.type) && (
          <ErrorBanner
            errorType={error.type}
            errorMessage={error.message}
            traceback={error.traceback}
            data-testid={`${testIdPrefix}-error-banner`}
          />
        )}

        <DetailStats cells={statsCells} data-testid={statsTestId} />

        <div class={styles.executionsSection}>
          <h3 class={styles.panelHeading}>{executionHeading}</h3>
          {executionLoading && !executionHasData ? (
            <Spinner />
          ) : (
            <ExecutionTable
              records={executionRecords}
              kind={executionKind}
              tableId={executionTableId}
              appKey={appKey}
              handlerKind={handlerKind}
              handlerId={handlerId}
              instanceQs={instanceQs}
            />
          )}
        </div>

        <div class={styles.footer}>
          <div class={styles.footerRow}>
            {sourceLocation && (
              <SourceLocation sourceLocation={sourceLocation} data-testid={`${testIdPrefix}-source-location`} />
            )}
            {onViewCode && sourceLocation && (
              <Button
                ghost
                size="sm"
                data-testid="view-in-code-btn"
                onClick={() => onViewCode(sourceLine ?? undefined)}
              >
                view in code →
              </Button>
            )}
          </div>

          {registrationSource && (
            <>
              <button
                type="button"
                class={styles.registrationToggle}
                data-testid={`${testIdPrefix}-registration-toggle`}
                aria-expanded={registrationExpanded}
                onClick={() => setRegistrationExpanded((v) => !v)}
              >
                {registrationExpanded ? "hide registration" : "registration"}
              </button>
              {registrationExpanded && (
                <RegistrationSource source={registrationSource} data-testid={`${testIdPrefix}-registration-source`} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
