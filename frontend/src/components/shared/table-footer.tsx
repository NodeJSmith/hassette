import clsx from "clsx";
import type { ReactNode } from "react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { FilterIcon } from "./filter-icon";
import styles from "./table-footer.module.css";
import type { ColumnFilters } from "./table-types";

interface TableFooterProps {
  count: ReactNode;
  columnFilters?: ColumnFilters;
  onResetFilters?: () => void;
  extras?: ReactNode;
}

export function TableFooter({ count, columnFilters, onResetFilters, extras }: TableFooterProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const [filterOpen, setFilterOpen] = useState(false);

  const hasActiveFilter = columnFilters ? Object.values(columnFilters).some((f) => f.active) : false;

  const showMobileFilterBtn = isMobile && columnFilters && Object.keys(columnFilters).length > 0;

  return (
    <div className={styles.footer}>
      <div className={styles.left}>
        <span className={styles.count} aria-live="polite">
          {count}
        </span>
      </div>
      <div className={styles.right}>
        {extras}
        {showMobileFilterBtn && columnFilters && (
          <Popover open={filterOpen} onOpenChange={setFilterOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={clsx(styles.filterBtn, hasActiveFilter && styles.filterBtnActive)}
                aria-label="Open filters"
                data-testid="mobile-filters-btn"
              >
                <FilterIcon active={hasActiveFilter} />
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" data-testid="table-footer-mobile-filters-popover" className="w-auto">
              <div className={styles.mobileFilters}>
                {Object.entries(columnFilters).map(([key, filter]) => (
                  <div key={key} className={styles.mobileFilterGroup}>
                    <label>{filter.label}</label>
                    {filter.content}
                  </div>
                ))}
                {onResetFilters && hasActiveFilter && (
                  <button
                    type="button"
                    className={styles.resetFiltersBtn}
                    onClick={onResetFilters}
                    aria-label="Reset filters"
                  >
                    Reset to defaults
                  </button>
                )}
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>
    </div>
  );
}
