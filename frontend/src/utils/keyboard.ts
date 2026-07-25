/** Call `callback` when Enter or Space is pressed, preventing default scroll/submit. */
export function onActivateKeyDown(callback: () => void): (e: KeyboardEvent) => void {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      callback();
    }
  };
}

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent);
export const SHORTCUT_HINT = IS_MAC ? "⌘K" : "Ctrl+K";
