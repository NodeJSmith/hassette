import clsx from "clsx";
import { useState } from "preact/hooks";
import { Link } from "wouter";

import { StatusShape } from "../shared/status-shape";
import styles from "./overview-tab.module.css";
import { handlerPath, itemErrorMessage, itemErrorType } from "./overview-tab-helpers";
import type { UnifiedItem } from "./unified-handler-row";

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
    <div class={styles.spotlightEntry} data-testid={`overview-spotlight-entry-${item.kind}-${item.id}`}>
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={12} />
      </span>
      <span class={styles.spotlightName}>{item.name}</span>
      {errorType && <span class={styles.spotlightErrorType}>{errorType}</span>}
      {errorMessage && (
        <span class={styles.spotlightErrorMsg} title={errorMessage}>
          {errorMessage}
        </span>
      )}
      <Link href={href} class={styles.spotlightLink}>
        view
      </Link>
    </div>
  );
}

export function ErrorSpotlight({
  failingItems,
  appKey,
  instanceQs,
}: {
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
      aria-label="failing handlers"
      data-testid="overview-error-spotlight"
    >
      {visibleItems.map((item) => (
        <SpotlightEntry key={`${item.kind}-${item.id}`} item={item} appKey={appKey} instanceQs={instanceQs} />
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
