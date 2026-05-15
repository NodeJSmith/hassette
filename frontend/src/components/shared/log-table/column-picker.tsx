import { useRef } from "preact/hooks";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { COLUMNS, REQUIRED_COLUMNS } from "./constants";
import type { ColumnId } from "./types";
import { ColumnFilterPopover } from "./column-filter";
import styles from "./column-picker.module.css";

interface Props {
  selectedColumns: ColumnId[];
  viewportHidden: ReadonlySet<ColumnId>;
  onToggle: (id: ColumnId) => void;
  onReset: () => void;
}

export function ColumnPicker({ selectedColumns, viewportHidden, onToggle, onReset }: Props) {
  const open = useSignal(false);
  useSubscribe(open);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        class={styles.trigger}
        onClick={() => { open.value = !open.value; }}
        aria-label="Choose visible columns"
        data-testid="column-picker"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.2" />
          <rect x="8" y="1" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.2" />
          <rect x="1" y="8" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.2" />
          <rect x="8" y="8" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
      <ColumnFilterPopover open={open.value} onClose={() => { open.value = false; }} triggerRef={triggerRef}>
        <div class={styles.list}>
          {COLUMNS.map((col) => {
            const isViewportHidden = viewportHidden.has(col.id);
            const isDisabled = REQUIRED_COLUMNS.has(col.id) || isViewportHidden;
            return (
              <label
                key={col.id}
                class={styles.item}
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
        <button type="button" class={styles.resetBtn} onClick={onReset}>
          Reset to defaults
        </button>
      </ColumnFilterPopover>
    </>
  );
}
