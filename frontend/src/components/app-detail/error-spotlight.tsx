import { useState } from "react";
import { Link } from "wouter";

import { cn } from "@/lib/utils";

import { StatusShape } from "../shared/status-shape";
import { OVERVIEW_SECTION_CLASS } from "./overview-section";
import { handlerHref, itemErrorMessage, itemErrorType } from "./overview-tab-helpers";
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
  const href = handlerHref(appKey, item, instanceQs);

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-[color-mix(in_srgb,var(--destructive)_30%,transparent)] bg-[var(--destructive-bg)] p-3"
      data-testid={`overview-spotlight-entry-${item.kind}-${item.id}`}
    >
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={12} />
      </span>
      <span className="shrink-0 whitespace-nowrap font-mono text-[length:var(--text-mono-sm)] font-medium text-foreground">
        {item.name}
      </span>
      {errorType && <span className="shrink-0 whitespace-nowrap text-sm text-destructive">{errorType}</span>}
      {errorMessage && (
        <span className="min-w-0 flex-1 truncate text-sm text-foreground-secondary" title={errorMessage}>
          {errorMessage}
        </span>
      )}
      <Link href={href} className="shrink-0 whitespace-nowrap text-sm text-primary hover:underline">
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
      className={cn(OVERVIEW_SECTION_CLASS, "flex flex-col gap-2")}
      aria-label="failing handlers"
      data-testid="overview-error-spotlight"
    >
      {visibleItems.map((item) => (
        <SpotlightEntry key={`${item.kind}-${item.id}`} item={item} appKey={appKey} instanceQs={instanceQs} />
      ))}
      {!expanded && hiddenCount > 0 && (
        <button
          type="button"
          className="px-3 py-2 text-left text-sm text-muted-foreground hover:text-foreground"
          data-testid="overview-spotlight-show-more"
          onClick={() => setExpanded(true)}
        >
          show {hiddenCount} more
        </button>
      )}
    </section>
  );
}
