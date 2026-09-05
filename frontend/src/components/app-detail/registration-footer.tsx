import { useState } from "react";

import { Button } from "@/components/ui/button";

import { parseSourceLocation } from "../../utils/format";
import { type ExecutionKind } from "../shared/execution-table";
import { IconArrowRight, IconChevron } from "../shared/icons";
import { RegistrationSource } from "../shared/registration-source";
import { SourceLocation } from "../shared/source-location";

interface RegistrationFooterProps {
  kind: ExecutionKind;
  testId: string;
  sourceLocation?: string | null;
  registrationSource?: string | null;
  onViewCode?: (line?: number) => void;
}

export function RegistrationFooter({
  kind,
  testId,
  sourceLocation,
  registrationSource,
  onViewCode,
}: RegistrationFooterProps) {
  const [registrationExpanded, setRegistrationExpanded] = useState(false);

  if (!sourceLocation && !registrationSource) {
    return null;
  }

  const sourceLine = sourceLocation ? parseSourceLocation(sourceLocation).line : null;
  const registrationPanelId = `${testId}-registration-source-panel`;
  const registrationHeadingId = `${testId}-registration-heading`;

  return (
    <section
      className="-mx-4 -mb-4 mt-5 flex flex-col gap-3 rounded-b-md border-t border-border bg-muted px-4 py-3"
      aria-labelledby={registrationHeadingId}
    >
      <div className="flex items-center justify-between gap-3 max-mobile:flex-col max-mobile:items-start">
        <div className="min-w-0 flex flex-col gap-1 [&_.text-muted-foreground]:text-foreground-secondary">
          <h3
            id={registrationHeadingId}
            className="m-0 font-mono text-xs font-medium uppercase tracking-[var(--text-label-tracking-wide)] text-muted-foreground"
          >
            Registration
          </h3>
          {sourceLocation && <SourceLocation sourceLocation={sourceLocation} data-testid={`${kind}-source-location`} />}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-1 max-mobile:-ml-1 max-mobile:justify-start">
          {onViewCode && sourceLocation && (
            <Button
              variant="info-ghost"
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
              variant="info-ghost"
              size="sm"
              data-testid={`${kind}-registration-toggle`}
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
          data-testid={`${kind}-registration-source`}
        />
      )}
    </section>
  );
}
