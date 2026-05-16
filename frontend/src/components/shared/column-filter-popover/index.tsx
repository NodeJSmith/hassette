import { useEffect, useRef } from "preact/hooks";
import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";
import type { ComponentChildren } from "preact";
import styles from "./index.module.css";

const FOCUSABLE_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS));
}

interface Props {
  open: boolean;
  onClose: () => void;
  triggerRef: preact.RefObject<HTMLElement | null>;
  label?: string;
  children: ComponentChildren;
}

export function ColumnFilterPopover({ open, onClose, triggerRef, label, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const ignoreNextClick = useRef(false);
  const wasOpen = useRef(false);

  // Floating-ui position management
  useEffect(() => {
    if (!open || !triggerRef.current || !popoverRef.current) return;

    const trigger = triggerRef.current;
    const popover = popoverRef.current;

    const cleanup = autoUpdate(trigger, popover, () => {
      void computePosition(trigger, popover, {
        strategy: "fixed",
        placement: "bottom-start",
        middleware: [offset(4), flip(), shift({ padding: 8 })],
      }).then(({ x, y }) => {
        popover.style.left = `${x}px`;
        popover.style.top = `${y}px`;
      });
    });

    return cleanup;
  }, [open, triggerRef]);

  // Focus management: focus first focusable child on open
  useEffect(() => {
    if (!open || !popoverRef.current) return;

    const focusables = getFocusableElements(popoverRef.current);
    if (focusables.length > 0) {
      focusables[0].focus();
    } else {
      popoverRef.current.focus();
    }
  }, [open]);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      return;
    }
    if (!wasOpen.current) return;
    triggerRef.current?.focus();
  }, [open, triggerRef]);

  // Keyboard and click-outside handlers
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }

      if (e.key === "Tab" && popoverRef.current) {
        const focusables = getFocusableElements(popoverRef.current);
        if (focusables.length === 0) return;

        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (e.shiftKey) {
          // Shift+Tab: if on first, wrap to last
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          // Tab: if on last, wrap to first
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    }

    function handleClickOutside(e: PointerEvent) {
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
    document.addEventListener("pointerdown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handleClickOutside);
    };
  }, [open, onClose, triggerRef]);

  if (!open) return null;

  return (
    <div
      ref={popoverRef}
      class={styles.popover}
      role="dialog"
      aria-label={label ?? "Column filter"}
      tabIndex={-1}
      onPointerDown={() => { ignoreNextClick.current = true; }}
    >
      {children}
    </div>
  );
}
