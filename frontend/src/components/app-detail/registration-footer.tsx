import { useState } from "preact/hooks";

import { parseSourceLocation } from "../../utils/format";
import { Button } from "../shared/button";
import { IconArrowRight, IconChevron } from "../shared/icons";
import { RegistrationSource } from "../shared/registration-source";
import { SourceLocation } from "../shared/source-location";
import styles from "./registration-footer.module.css";

interface RegistrationFooterProps {
  kind: "handler" | "job";
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
    <section class={styles.footer} aria-labelledby={registrationHeadingId}>
      <div class={styles.footerSummary}>
        <div class={styles.footerIdentity}>
          <h3 id={registrationHeadingId} class={styles.footerLabel}>
            Registration
          </h3>
          {sourceLocation && <SourceLocation sourceLocation={sourceLocation} data-testid={`${kind}-source-location`} />}
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
