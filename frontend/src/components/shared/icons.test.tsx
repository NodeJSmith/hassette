import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IconArrowRight, IconChevron, IconPlay, IconRefresh, IconSquare, IconWarning } from "./icons";

/** Every icon built on the shared `StrokeIcon` wrapper. `IconChevron` renders its own svg, so it is tested separately. */
const STROKE_ICONS = [IconPlay, IconSquare, IconRefresh, IconArrowRight, IconWarning];

const STROKE_ICON_CASES = STROKE_ICONS.map((Icon) => [Icon.name, Icon] as const);

describe("Icons smoke tests", () => {
  it.each(STROKE_ICON_CASES)("%s renders an SVG element", (_name, Icon) => {
    const { container } = render(<Icon />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it.each(STROKE_ICON_CASES)("%s carries the shared wrapper classes", (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("class")?.split(/\s+/)).toEqual(
      expect.arrayContaining(["size-4", "shrink-0", "align-middle"]),
    );
  });

  it.each(STROKE_ICON_CASES)("%s has aria-hidden='true'", (_name, Icon) => {
    const { container } = render(<Icon />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("IconChevron is aria-hidden and swaps its points on open", () => {
    const closed = render(<IconChevron open={false} />);
    const closedSvg = closed.container.querySelector("svg");
    expect(closedSvg?.getAttribute("aria-hidden")).toBe("true");
    const closedPoints = closedSvg?.querySelector("polyline")?.getAttribute("points");

    const opened = render(<IconChevron open={true} />);
    const openedSvg = opened.container.querySelector("svg");
    expect(openedSvg?.getAttribute("aria-hidden")).toBe("true");
    const openedPoints = openedSvg?.querySelector("polyline")?.getAttribute("points");

    expect(closedPoints).toBeTruthy();
    expect(openedPoints).toBeTruthy();
    expect(openedPoints).not.toBe(closedPoints);
  });
});
