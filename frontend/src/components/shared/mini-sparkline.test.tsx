import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { MiniSparkline } from "./mini-sparkline";

describe("MiniSparkline", () => {
  it("returns null for empty buckets", () => {
    const { container } = render(<MiniSparkline buckets={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("returns null for a single bucket (needs >=2 for a line)", () => {
    const { container } = render(<MiniSparkline buckets={[{ ok: 5, err: 0 }]} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders an SVG polyline for two or more buckets", () => {
    const { container } = render(
      <MiniSparkline
        buckets={[
          { ok: 10, err: 0 },
          { ok: 5, err: 0 },
        ]}
      />,
    );
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg!.querySelector("polyline")).toBeTruthy();
  });

  it("renders error dots for buckets with errors", () => {
    const { container } = render(
      <MiniSparkline
        buckets={[
          { ok: 10, err: 0 },
          { ok: 5, err: 3 },
        ]}
      />,
    );
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(1);
  });

  it("does not render error dots when no errors", () => {
    const { container } = render(
      <MiniSparkline
        buckets={[
          { ok: 10, err: 0 },
          { ok: 5, err: 0 },
        ]}
      />,
    );
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(0);
  });

  it("respects custom width and height", () => {
    const { container } = render(
      <MiniSparkline
        buckets={[
          { ok: 1, err: 0 },
          { ok: 2, err: 0 },
        ]}
        width={100}
        height={30}
      />,
    );
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("width")).toBe("100");
    expect(svg!.getAttribute("height")).toBe("30");
  });
});
