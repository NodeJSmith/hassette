/** Call `callback` when Enter or Space is pressed, preventing default scroll/submit. */
export function onActivateKeyDown(callback: () => void): (e: KeyboardEvent) => void {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      callback();
    }
  };
}
