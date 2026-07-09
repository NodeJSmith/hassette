// Shared SVG icon components
// Sidebar icons use fill-based paths (no stroke attributes).
// All other icons use stroke-based attributes.
import styles from "./icons.module.css";

// --- Stroke-based icons ---

export const IconPlay = () => (
  <svg
    class={styles.iconSvg}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <polygon points="6 3 20 12 6 21 6 3" />
  </svg>
);

export const IconSquare = () => (
  <svg
    class={styles.iconSvg}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <rect width="14" height="14" x="5" y="5" rx="2" />
  </svg>
);

export const IconRefresh = () => (
  <svg
    class={styles.iconSvg}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M8 16H3v5" />
  </svg>
);

export const IconWarning = () => (
  <svg
    class={styles.iconSvg}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </svg>
);

/** Small inline chevron for expand/collapse toggles. */
export const IconChevron = ({ open, size = 10 }: { open: boolean; size?: number }) => (
  <svg viewBox="0 0 12 12" width={size} height={size} aria-hidden="true">
    <polyline points={open ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
  </svg>
);
