// Shared SVG icon components
import type { ReactNode } from "react";

/** Shared 24x24 stroke-style wrapper — every stroke icon differs only in its inner shape. */
function StrokeIcon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="size-4 shrink-0 align-middle"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const IconPlay = () => (
  <StrokeIcon>
    <polygon points="6 3 20 12 6 21 6 3" />
  </StrokeIcon>
);

export const IconSquare = () => (
  <StrokeIcon>
    <rect width="14" height="14" x="5" y="5" rx="2" />
  </StrokeIcon>
);

export const IconRefresh = () => (
  <StrokeIcon>
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M8 16H3v5" />
  </StrokeIcon>
);

export const IconArrowRight = () => (
  <StrokeIcon>
    <path d="M5 12h14" />
    <path d="m13 6 6 6-6 6" />
  </StrokeIcon>
);

export const IconWarning = () => (
  <StrokeIcon>
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </StrokeIcon>
);

export const IconClose = () => (
  <StrokeIcon>
    <line x1="6" y1="6" x2="18" y2="18" />
    <line x1="18" y1="6" x2="6" y2="18" />
  </StrokeIcon>
);

export const IconMenu = () => (
  <StrokeIcon>
    <line x1="3" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="21" y2="12" />
    <line x1="3" y1="18" x2="21" y2="18" />
  </StrokeIcon>
);

/** Points right: "go that way" (e.g. re-open the sidebar), not an open/closed disclosure state. */
export const IconChevronRight = () => (
  <StrokeIcon>
    <polyline points="9,4.5 16.5,12 9,19.5" />
  </StrokeIcon>
);

export const IconSun = () => (
  <StrokeIcon>
    <circle cx="12" cy="12" r="5" />
    <line x1="12" y1="1" x2="12" y2="3" />
    <line x1="12" y1="21" x2="12" y2="23" />
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
    <line x1="1" y1="12" x2="3" y2="12" />
    <line x1="21" y1="12" x2="23" y2="12" />
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
  </StrokeIcon>
);

export const IconMoon = () => (
  <StrokeIcon>
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
  </StrokeIcon>
);

/** Small inline chevron for expand/collapse toggles. */
export const IconChevron = ({ open }: { open: boolean }) => (
  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
    <polyline points={open ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
