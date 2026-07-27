/**
 * Tab-key focus wrap: when Tab is pressed on the last focusable element, wraps to
 * the first; when Shift+Tab is pressed on the first, wraps to the last. Call from a
 * `keydown` handler when `e.key === "Tab"`. No-op if `focusable` is empty.
 *
 * Callers own how they collect `focusable` — a fixed set of refs (a dialog with a
 * known button pair) and a live DOM query (a popover with arbitrary children) both
 * feed the same wrap logic.
 */
export function wrapFocusOnTab(e: KeyboardEvent, focusable: HTMLElement[]): void {
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
