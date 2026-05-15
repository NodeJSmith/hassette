import { useEffect, useRef } from "preact/hooks";
import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";
import type { ComponentChildren } from "preact";
import styles from "./column-filter.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
  triggerRef: preact.RefObject<HTMLElement | null>;
  children: ComponentChildren;
}

export function ColumnFilterPopover({ open, onClose, triggerRef, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const ignoreNextClick = useRef(false);

  useEffect(() => {
    if (!open || !triggerRef.current || !popoverRef.current) return;

    const trigger = triggerRef.current;
    const popover = popoverRef.current;

    const cleanup = autoUpdate(trigger, popover, () => {
      computePosition(trigger, popover, {
        placement: "bottom-start",
        middleware: [offset(4), flip(), shift({ padding: 8 })],
      }).then(({ x, y }) => {
        popover.style.left = `${x}px`;
        popover.style.top = `${y}px`;
      });
    });

    return cleanup;
  }, [open, triggerRef]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    }

    function handleClickOutside(e: MouseEvent) {
      if (ignoreNextClick.current) {
        ignoreNextClick.current = false;
        return;
      }
      if (
        popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open, onClose, triggerRef]);

  if (!open) return null;

  return (
    <div
      ref={popoverRef}
      class={styles.popover}
      role="dialog"
      aria-label="Column filter"
      onMouseDown={() => { ignoreNextClick.current = true; }}
      onPointerDown={() => { ignoreNextClick.current = true; }}
    >
      {children}
    </div>
  );
}
