import { SMALL_ICON_SIZE } from "../../utils/constants";
import type { StatusKind } from "../../utils/status";

interface Props {
  kind: StatusKind;
  size?: number;
  muted?: boolean;
}

const CORNER_RADIUS_RATIO = 0.2;
const RING_STROKE_WIDTH = 1.5;

function renderShape(kind: StatusKind, size: number, half: number) {
  switch (kind) {
    case "ok":
      return <circle cx={half} cy={half} r={half} fill="var(--ok-vivid)" />;
    case "warn": {
      // Equilateral triangle, pointing up, centered in bounding box
      const pts = `${half},1 ${size - 1},${size - 1} 1,${size - 1}`;
      return <polygon points={pts} fill="var(--warn-vivid)" />;
    }
    case "err": {
      const r = size * CORNER_RADIUS_RATIO;
      return <rect x="1" y="1" width={size - 2} height={size - 2} rx={r} ry={r} fill="var(--err-vivid)" />;
    }
    case "cancel": {
      // Diamond (square rotated 45°), centered in bounding box
      const pts = `${half},1 ${size - 1},${half} ${half},${size - 1} 1,${half}`;
      return <polygon points={pts} fill="var(--cancel-vivid)" />;
    }
    case "mute":
      // ring (stroke-only circle)
      return (
        <circle
          cx={half}
          cy={half}
          r={half - RING_STROKE_WIDTH}
          fill="none"
          stroke="var(--mute)"
          strokeWidth={RING_STROKE_WIDTH}
        />
      );
  }
}

/**
 * SVG status shape indicator.
 *
 * - ok     → filled circle (green)
 * - warn   → filled triangle (amber)
 * - err    → filled rounded square (red)
 * - cancel → filled diamond (info blue)
 * - mute   → ring / stroke-only circle (muted)
 */
export function StatusShape({ kind, size = SMALL_ICON_SIZE, muted = false }: Props) {
  const half = size / 2;
  const shape = muted ? <circle cx={half} cy={half} r={half} fill="var(--ink-4)" /> : renderShape(kind, size, half);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      focusable="false"
      style={{ flexShrink: 0 }}
    >
      {shape}
    </svg>
  );
}
