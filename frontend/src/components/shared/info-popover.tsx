import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";
import { useEffect, useId, useRef, useState } from "preact/hooks";

import styles from "./info-popover.module.css";

interface Props {
  /** Help text to reveal when the info button is clicked. */
  text: string;
  /** Name of the thing being described, used in the trigger's accessible label. */
  label?: string;
}

/**
 * Click-triggered info popover: an ⓘ button that reveals wrapping help text on demand.
 *
 * Keeps verbose descriptions off the row so the field list stays scannable. Positioned
 * with floating-ui (flips and shifts to stay on-screen); dismisses on Escape or an
 * outside click. The trigger is a real button so it is reachable by keyboard and touch.
 */
export function InfoPopover({ text, label = "field" }: Props) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  // Position the popover under the trigger and keep it anchored on scroll/resize.
  useEffect(() => {
    if (!open || !triggerRef.current || !popRef.current) return;
    const trigger = triggerRef.current;
    const pop = popRef.current;
    return autoUpdate(trigger, pop, () => {
      void computePosition(trigger, pop, {
        strategy: "fixed",
        placement: "bottom",
        middleware: [offset(6), flip(), shift({ padding: 8 })],
      }).then(({ x, y }) => {
        pop.style.left = `${x}px`;
        pop.style.top = `${y}px`;
      });
    });
  }, [open]);

  // Dismiss on Escape or a click outside the trigger/popover.
  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Don't let Escape also reach a parent dialog/panel listener.
        e.stopPropagation();
        setOpen(false);
      }
    }
    function onPointerDown(e: PointerEvent) {
      const target = e.target;
      if (!(target instanceof Node)) return;
      if (popRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    }

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    // aria-live announces the popover text to screen readers when it appears,
    // without stealing focus; aria-controls links the button to the content.
    <span class={styles.wrap} aria-live="polite">
      <button
        ref={triggerRef}
        type="button"
        class={styles.trigger}
        aria-label={open ? `Hide ${label} description` : `Show ${label} description`}
        aria-expanded={open}
        aria-controls={popId}
        onClick={() => setOpen((prev) => !prev)}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5" />
          <line x1="8" y1="7.5" x2="8" y2="11.5" stroke="currentColor" stroke-width="1.5" />
          <circle cx="8" cy="4.5" r="0.95" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div id={popId} ref={popRef} class={styles.pop} role="note" data-testid="field-help">
          {text}
        </div>
      )}
    </span>
  );
}
