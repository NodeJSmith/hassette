import { useState } from "preact/hooks";
import { Link } from "wouter";
import clsx from "clsx";
import { StatusShape } from "../shared/status-shape";
import type { UnifiedItem } from "./unified-handler-row";
import { handlerPath, itemErrorType, itemErrorMessage } from "./overview-tab-helpers";
import styles from "./overview-tab.module.css";

const SPOTLIGHT_LIMIT = 3;

interface SpotlightEntryProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}

function SpotlightEntry({ item, appKey, instanceQs }: SpotlightEntryProps) {
  const errorType = itemErrorType(item);
  const errorMessage = itemErrorMessage(item);
  const href = handlerPath(appKey, item, instanceQs);

  return (
    <div
      class={styles.spotlightEntry}
      data-testid={`overview-spotlight-entry-${item.kind}-${item.id}`}
    >
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={12} />
      </span>
      <div class={styles.spotlightBody}>
        <div class={styles.spotlightHeader}>
          <span class={styles.spotlightName}>{item.name}</span>
          {errorType && (
            <span class={styles.spotlightErrorType}>{errorType}</span>
          )}
        </div>
        {errorMessage && (
          <div class={styles.spotlightErrorMsg} title={errorMessage}>
            {errorMessage}
          </div>
        )}
      </div>
      <Link href={href} class={styles.spotlightLink}>
        view
      </Link>
    </div>
  );
}

export function ErrorSpotlight({ failingItems, appKey, instanceQs }: {
  failingItems: UnifiedItem[];
  appKey: string;
  instanceQs: string;
}) {
  const [expanded, setExpanded] = useState(false);

  const visibleItems = expanded ? failingItems : failingItems.slice(0, SPOTLIGHT_LIMIT);
  const hiddenCount = failingItems.length - SPOTLIGHT_LIMIT;

  return (
    <section
      class={clsx(styles.section, styles.spotlight)}
      data-testid="overview-error-spotlight"
    >
      <h3 class="ht-section-label">failing handlers</h3>
      {visibleItems.map((item) => (
        <SpotlightEntry
          key={`${item.kind}-${item.id}`}
          item={item}
          appKey={appKey}
          instanceQs={instanceQs}
        />
      ))}
      {!expanded && hiddenCount > 0 && (
        <button
          type="button"
          class={styles.spotlightShowMore}
          data-testid="overview-spotlight-show-more"
          onClick={() => setExpanded(true)}
        >
          show {hiddenCount} more
        </button>
      )}
    </section>
  );
}
