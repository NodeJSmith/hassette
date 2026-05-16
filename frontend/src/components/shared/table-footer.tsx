import { useRef } from "preact/hooks";
import type { ComponentChildren } from "preact";
import clsx from "clsx";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { useSignal } from "../../hooks/use-signal";
import { useSubscribe } from "../../hooks/use-subscribe";
import { ColumnFilterPopover } from "./column-filter-popover/index";
import { FilterIcon } from "./filter-icon";
import type { ColumnFilters } from "./table-types";
import styles from "./table-footer.module.css";

interface TableFooterProps {
  count: ComponentChildren;
  columnFilters?: ColumnFilters;
  onResetFilters?: () => void;
  extras?: ComponentChildren;
}

export function TableFooter({
  count,
  columnFilters,
  onResetFilters,
  extras,
}: TableFooterProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const filterOpen = useSignal(false);
  useSubscribe(filterOpen);
  const filterTriggerRef = useRef<HTMLButtonElement>(null);

  const hasActiveFilter = columnFilters
    ? Object.values(columnFilters).some((f) => f.active)
    : false;

  const showMobileFilterBtn = isMobile && columnFilters && Object.keys(columnFilters).length > 0;

  return (
    <div class={styles.footer}>
      <div class={styles.left}>
        <span class={styles.count} aria-live="polite">{count}</span>
      </div>
      <div class={styles.right}>
        {extras}
        {showMobileFilterBtn && columnFilters && (
          <>
            <button
              ref={filterTriggerRef}
              type="button"
              class={clsx(styles.filterBtn, hasActiveFilter && styles.filterBtnActive)}
              onClick={() => { filterOpen.value = !filterOpen.value; }}
              aria-label="Open filters"
              data-testid="mobile-filters-btn"
            >
              <FilterIcon active={hasActiveFilter} />
            </button>
            <ColumnFilterPopover
              open={filterOpen.value}
              onClose={() => { filterOpen.value = false; }}
              triggerRef={filterTriggerRef}
            >
              <div class={styles.mobileFilters}>
                {Object.entries(columnFilters).map(([key, filter]) => (
                  <div key={key} class={styles.mobileFilterGroup}>
                    <label>{filter.label}</label>
                    {filter.content}
                  </div>
                ))}
                {onResetFilters && hasActiveFilter && (
                  <button
                    type="button"
                    class={styles.resetFiltersBtn}
                    onClick={onResetFilters}
                    aria-label="Reset filters"
                  >
                    Reset to defaults
                  </button>
                )}
              </div>
            </ColumnFilterPopover>
          </>
        )}
      </div>
    </div>
  );
}
