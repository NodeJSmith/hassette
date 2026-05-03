import { useEffect, useRef } from "preact/hooks";

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
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  tone = "default",
}: Props) {
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
        const focusable = [cancelRef.current, confirmRef.current].filter(
          (el): el is HTMLButtonElement => el !== null,
        );
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  const idRef = useRef(Math.random().toString(36).slice(2, 8));
  const titleId = `confirm-dialog-title-${idRef.current}`;
  const bodyId = `confirm-dialog-body-${idRef.current}`;

  return (
    <>
      <div class="confirm-dialog__backdrop" onClick={onCancel} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        class="confirm-dialog"
      >
        <h2 id={titleId} class="confirm-dialog__title">
          {title}
        </h2>
        <p id={bodyId} class="confirm-dialog__body">
          {body}
        </p>
        <div class="confirm-dialog__actions">
          <button
            type="button"
            ref={cancelRef}
            class="confirm-dialog__cancel"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            ref={confirmRef}
            class={`confirm-dialog__confirm${tone === "danger" ? " confirm-dialog__confirm--danger" : ""}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  );
}
