import type { StatusKind } from "../../utils/status";

interface Props {
  kind: StatusKind;
  size?: number;
}

/**
 * SVG status shape indicator.
 *
 * - ok   → filled circle (green)
 * - warn → filled triangle (amber)
 * - err  → filled rounded square (red)
 * - mute → ring / stroke-only circle (muted)
 */
export function StatusShape({ kind, size = 12 }: Props) {
  const half = size / 2;

  if (kind === "ok") {
    return (
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        focusable="false"
      >
        <circle cx={half} cy={half} r={half} fill="var(--ok)" />
      </svg>
    );
  }

  if (kind === "warn") {
    // Equilateral triangle, pointing up, centered in bounding box
    const pts = `${half},1 ${size - 1},${size - 1} 1,${size - 1}`;
    return (
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        focusable="false"
      >
        <polygon points={pts} fill="var(--warn)" />
      </svg>
    );
  }

  if (kind === "err") {
    const r = size * 0.2;
    return (
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        focusable="false"
      >
        <rect x="1" y="1" width={size - 2} height={size - 2} rx={r} ry={r} fill="var(--err)" />
      </svg>
    );
  }

  // mute → ring (stroke-only circle)
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      focusable="false"
    >
      <circle
        cx={half}
        cy={half}
        r={half - 1.5}
        fill="none"
        stroke="var(--mute)"
        stroke-width="1.5"
      />
    </svg>
  );
}
