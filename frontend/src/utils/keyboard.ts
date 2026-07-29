import type { KeyboardEvent as ReactKeyboardEvent } from "react";

/** Call `callback` when Enter or Space is pressed, preventing default scroll/submit. */
export function onActivateKeyDown(callback: () => void): (e: ReactKeyboardEvent) => void {
  return (e: ReactKeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      callback();
    }
  };
}

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent);
export const SHORTCUT_HINT = IS_MAC ? "⌘K" : "Ctrl+K";
