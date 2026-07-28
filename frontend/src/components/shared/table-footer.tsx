import type { ReactNode } from "react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

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
              <button
                type="button"
                className={cn(
                  "inline-flex items-center rounded-sm border border-border bg-transparent p-1 text-muted-foreground transition-colors",
                  "hover:bg-[var(--highlight-bg)] hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                  hasActiveFilter && "border-[var(--primary-border)] text-primary",
                )}
                aria-label="Open filters"
                data-testid="mobile-filters-btn"
              >
                <FilterIcon active={hasActiveFilter} />
              </button>
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
                  <button
                    type="button"
                    className="self-start text-sm text-primary underline underline-offset-2"
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
