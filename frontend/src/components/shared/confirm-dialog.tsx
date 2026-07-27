import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

import { wrapFocusOnTab } from "../../utils/focus-trap";
import styles from "./confirm-dialog.module.css";

interface Props {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  tone?: "default" | "danger";
}

/**
 * Modal confirm dialog with focus trap and keyboard support.
 *
 * - Focus is moved to the Cancel button on mount and restored on unmount.
 * - Tab key is trapped within the dialog.
 * - Escape key calls onCancel.
 * - Uses semantic ARIA roles for screen reader accessibility.
 */
export function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel, tone = "default" }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Save previous focus and move focus to Cancel on mount
    previousFocusRef.current = document.activeElement as HTMLElement;
    cancelRef.current?.focus();

    return () => {
      // Restore previous focus on unmount
      previousFocusRef.current?.focus();
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }

      if (e.key === "Tab") {
        const focusable = [cancelRef.current, confirmRef.current].filter((el): el is HTMLButtonElement => el !== null);
        wrapFocusOnTab(e, focusable);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  const idRef = useRef(Math.random().toString(36).slice(2, 8));
  const titleId = `ht-confirm-dialog-title-${idRef.current}`;
  const bodyId = `ht-confirm-dialog-body-${idRef.current}`;

  return (
    <>
      <div className={styles.backdrop} data-testid="confirm-dialog-backdrop" onClick={onCancel} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        className={styles.dialog}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <p id={bodyId} className={styles.body}>
          {body}
        </p>
        <div className={styles.actions}>
          <Button
            variant="outline"
            ref={(el) => {
              cancelRef.current = el;
            }}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "default"}
            ref={(el) => {
              confirmRef.current = el;
            }}
            data-testid={tone === "danger" ? "confirm-btn-danger" : "confirm-btn"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </>
  );
}
