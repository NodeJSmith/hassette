import type { ReactNode } from "react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { FilterIcon } from "./filter-icon";
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
    <div className="flex items-center justify-between gap-3 px-1 pt-2 text-sm text-muted-foreground max-mobile:flex-col max-mobile:items-stretch">
      <div className="min-w-0">
        <span className="block" aria-live="polite">
          {count}
        </span>
      </div>
      <div className="flex items-center gap-2 max-mobile:w-full max-mobile:justify-between">
        {extras}
        {showMobileFilterBtn && columnFilters && (
          <Popover open={filterOpen} onOpenChange={setFilterOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="subtle"
                size="icon-xs"
                className={
                  hasActiveFilter ? "border-[var(--primary-border)] text-primary hover:text-primary" : undefined
                }
                aria-label="Open filters"
                data-testid="mobile-filters-btn"
              >
                <FilterIcon active={hasActiveFilter} />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" data-testid="table-footer-mobile-filters-popover" className="w-auto">
              <div className="flex min-w-[220px] flex-col gap-3">
                {Object.entries(columnFilters).map(([key, filter]) => (
                  <div key={key} className="flex flex-col gap-1">
                    <label className="text-xs font-medium uppercase tracking-[var(--text-label-tracking)] text-muted-foreground">
                      {filter.label}
                    </label>
                    {filter.content}
                  </div>
                ))}
                {onResetFilters && hasActiveFilter && (
                  <Button
                    variant="link-muted"
                    size="inline"
                    className="self-start"
                    onClick={onResetFilters}
                    aria-label="Reset filters"
                  >
                    Reset to defaults
                  </Button>
                )}
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>
    </div>
  );
}
