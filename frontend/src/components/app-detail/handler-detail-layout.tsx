import type { ReadonlySignal } from "@preact/signals";
import type { ComponentChildren } from "preact";

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
  nameAutoHint?: boolean;
  subtitle?: string | null;
  registrationSource?: string | null;
  chips?: ComponentChildren;
  extras?: ComponentChildren;
  sourceLocation?: string | null;
  onViewCode?: (line?: number) => void;
  error?: ErrorInfo | null;
  statsCells: DetailStatsCell[];
  statsTestId: string;
  executionHeading: string;
  executionRecords: ExecutionRecord[];
  executionKind: "handler" | "job";
  executionTableId: string;
  executionLoading: ReadonlySignal<boolean>;
  executionHasData: boolean;
}

export function HandlerDetailLayout({
  testId,
  testIdPrefix,
  kindLabel,
  statusKind,
  name,
  nameAutoHint,
  subtitle,
  registrationSource,
  chips,
  extras,
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
}: Props) {
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
          <span class={styles.handlerName}>
            {name}
            {nameAutoHint && (
              <span
                class={styles.nameAutoHint}
                title={`Auto-generated name. Pass name="..." when scheduling for something descriptive.`}
                aria-label="Auto-generated name"
              >
                ⓘ
              </span>
            )}
          </span>
          {isFailing && (
            <Badge variant="danger" size="sm" data-testid="handler-status-pill">
              failing
            </Badge>
          )}
        </div>

        {subtitle && (
          <p class={styles.subtitle} data-testid={`${testIdPrefix}-human-description`}>
            {subtitle}
          </p>
        )}

        {registrationSource && (
          <RegistrationSource source={registrationSource} data-testid={`${testIdPrefix}-registration-source`} />
        )}

        {chips}

        {extras}

        {sourceLocation && (
          <SourceLocation sourceLocation={sourceLocation} data-testid={`${testIdPrefix}-source-location`} />
        )}

        {isFailing && error && (error.message || error.type) && (
          <ErrorBanner
            errorType={error.type}
            errorMessage={error.message}
            traceback={error.traceback}
            data-testid={`${testIdPrefix}-error-banner`}
          />
        )}

        <DetailStats cells={statsCells} data-testid={statsTestId} />

        {onViewCode && sourceLocation && (
          <Button ghost size="sm" data-testid="view-in-code-btn" onClick={() => onViewCode(sourceLine ?? undefined)}>
            view in code →
          </Button>
        )}
      </div>

      <div class={styles.executionsPanel}>
        <h3 class={styles.panelHeading}>{executionHeading}</h3>
        {executionLoading.value && !executionHasData ? (
          <Spinner />
        ) : (
          <ExecutionTable records={executionRecords} kind={executionKind} tableId={executionTableId} />
        )}
      </div>
    </div>
  );
}
