import { autoUpdate, computePosition, flip, offset, shift, size } from "@floating-ui/dom";
import clsx from "clsx";
import type { ReactNode, RefObject } from "react";
import { useEffect, useRef, useState } from "react";

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
  triggerRef: RefObject<HTMLElement | null>;
  label?: string;
  children: ReactNode;
}

export function ColumnFilterPopover({ open, onClose, triggerRef, label, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const ignoreNextClick = useRef(false);
  const wasOpen = useRef(false);
  // Gates visibility until computePosition() lands, so the popover is never painted at its
  // pre-computation origin.
  const [positioned, setPositioned] = useState(false);

  // Floating-ui position management
  useEffect(() => {
    if (!open || !triggerRef.current || !popoverRef.current) {
      setPositioned(false);
      return;
    }

    const trigger = triggerRef.current;
    const popover = popoverRef.current;
    // A computePosition() promise can resolve after close; without this the next open would
    // start already-visible and paint at the stale position for a frame.
    let closed = false;

    const cleanup = autoUpdate(trigger, popover, () => {
      void computePosition(trigger, popover, {
        strategy: "fixed",
        placement: "bottom-start",
        middleware: [
          offset(4),
          flip(),
          shift({ padding: 8 }),
          // static CSS max-height defeats flip() — size() sets it dynamically after placement is chosen
          size({
            padding: 8,
            apply({ availableHeight, elements }) {
              elements.floating.style.maxHeight = `${Math.max(0, availableHeight)}px`;
            },
          }),
        ],
      }).then(({ x, y }) => {
        if (closed) return;
        popover.style.left = `${x}px`;
        popover.style.top = `${y}px`;
        setPositioned(true);
      });
    });

    return () => {
      closed = true;
      cleanup();
    };
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
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
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
      className={clsx(styles.popover, positioned && styles.positioned)}
      role="dialog"
      aria-label={label ?? "Column filter"}
      tabIndex={-1}
      data-testid="column-picker-popover"
      onPointerDown={() => {
        ignoreNextClick.current = true;
      }}
    >
      {children}
    </div>
  );
}
