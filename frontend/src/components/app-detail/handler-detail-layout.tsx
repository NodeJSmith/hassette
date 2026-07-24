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
import { IconArrowRight, IconChevron } from "../shared/icons";
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
  const registrationPanelId = `${testId}-registration-source-panel`;
  const registrationHeadingId = `${testId}-registration-heading`;

  return (
    <div class={styles.wrapper} data-testid={testId}>
      <div class={styles.content}>
        <div class={styles.header}>
          <h2 class={styles.handlerName}>{name}</h2>
          {isFailing && (
            <Badge variant="danger" size="sm" data-testid="handler-status-pill">
              failing
            </Badge>
          )}
          {headerActions && <div class={styles.headerActions}>{headerActions}</div>}
        </div>

        <div class={styles.subtitle}>
          <Chip variant="kind" kind={statusKind} aria-label={`kind: ${kindLabel}`}>
            <StatusShape kind={statusKind} size={8} />
            {kindLabel}
          </Chip>
          {subtitle && <span data-testid={`${testIdPrefix}-human-description`}>{subtitle}</span>}
        </div>

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

        {(sourceLocation || registrationSource) && (
          <section class={styles.footer} aria-labelledby={registrationHeadingId}>
            <div class={styles.footerSummary}>
              <div class={styles.footerIdentity}>
                <h3 id={registrationHeadingId} class={styles.footerLabel}>
                  Registration
                </h3>
                {sourceLocation && (
                  <SourceLocation sourceLocation={sourceLocation} data-testid={`${testIdPrefix}-source-location`} />
                )}
              </div>

              <div class={styles.footerActions}>
                {onViewCode && sourceLocation && (
                  <Button
                    variant="info"
                    ghost
                    size="sm"
                    data-testid="view-in-code-btn"
                    onClick={() => onViewCode(sourceLine ?? undefined)}
                  >
                    view in code
                    <IconArrowRight />
                  </Button>
                )}
                {registrationSource && (
                  <Button
                    variant="info"
                    ghost
                    size="sm"
                    data-testid={`${testIdPrefix}-registration-toggle`}
                    aria-expanded={registrationExpanded}
                    aria-controls={registrationPanelId}
                    onClick={() => setRegistrationExpanded((v) => !v)}
                  >
                    {registrationExpanded ? "hide call" : "show call"}
                    <IconChevron open={registrationExpanded} />
                  </Button>
                )}
              </div>
            </div>

            {registrationSource && registrationExpanded && (
              <RegistrationSource
                id={registrationPanelId}
                source={registrationSource}
                data-testid={`${testIdPrefix}-registration-source`}
              />
            )}
          </section>
        )}
      </div>
    </div>
  );
}
