import { useRef } from "preact/hooks";
import clsx from "clsx";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { COLUMNS } from "./constants";
import type { ColumnId } from "./types";
import { ColumnFilterPopover } from "./column-filter";
import styles from "./column-picker.module.css";

interface Props {
  visibleColumns: ColumnId[];
  onToggle: (id: ColumnId) => void;
  onReset: () => void;
}

export function ColumnPicker({ visibleColumns, onToggle, onReset }: Props) {
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
          {COLUMNS.map((col) => (
            <label key={col.id} class={styles.item}>
              <span>{col.label}</span>
              <input
                type="checkbox"
                checked={visibleColumns.includes(col.id)}
                onChange={() => onToggle(col.id)}
                disabled={col.id === "level" || col.id === "message"}
              />
            </label>
          ))}
        </div>
        <button type="button" class={styles.resetBtn} onClick={onReset}>
          Reset to defaults
        </button>
      </ColumnFilterPopover>
    </>
  );
}
