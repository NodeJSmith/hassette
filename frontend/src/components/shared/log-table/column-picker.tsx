import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { COLUMNS, REQUIRED_COLUMNS } from "./constants";
import type { ColumnId } from "./types";

// Hover and focus-ring affordance shared by this popover's two chrome-less buttons, so the
// pair cannot drift apart. Per-button layout and sizing stay at the call sites.
const BARE_BUTTON_CLASS =
  "cursor-pointer border-none bg-transparent text-muted-foreground transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";

export interface ColumnPickerProps {
  selectedColumns: ColumnId[];
  viewportHidden: ReadonlySet<ColumnId>;
  onToggle: (id: ColumnId) => void;
  onReset: () => void;
}

export function ColumnPicker({ selectedColumns, viewportHidden, onToggle, onReset }: ColumnPickerProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(BARE_BUTTON_CLASS, "inline-flex items-center rounded-sm p-1")}
          aria-label="Choose visible columns"
          data-testid="column-picker"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" />
            <rect x="8" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" />
            <rect x="1" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" />
            <rect x="8" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" data-testid="column-picker-popover" className="w-auto">
        <div className="mb-2 flex flex-col gap-1">
          {COLUMNS.map((col) => {
            const isViewportHidden = viewportHidden.has(col.id);
            const isDisabled = REQUIRED_COLUMNS.has(col.id) || isViewportHidden;
            return (
              <label
                key={col.id}
                className="flex cursor-pointer items-center justify-between gap-2 text-sm text-foreground has-[:disabled]:cursor-default has-[:disabled]:text-muted-foreground [&_input[type=checkbox]]:accent-[var(--primary)]"
                title={isViewportHidden ? "Hidden at this screen size" : undefined}
              >
                <span>{col.label}</span>
                <input
                  type="checkbox"
                  checked={selectedColumns.includes(col.id)}
                  onChange={() => onToggle(col.id)}
                  disabled={isDisabled}
                />
              </label>
            );
          })}
        </div>
        <button type="button" className={cn(BARE_BUTTON_CLASS, "px-0 py-1 text-xs")} onClick={onReset}>
          Reset to defaults
        </button>
      </PopoverContent>
    </Popover>
  );
}
