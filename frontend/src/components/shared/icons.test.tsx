import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { IconPlay, IconRefresh, IconSquare, IconWarning } from "./icons";

describe("Icons smoke tests", () => {
  it("IconPlay renders an SVG element", () => {
    const { container } = render(<IconPlay />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconSquare renders an SVG element", () => {
    const { container } = render(<IconSquare />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconRefresh renders an SVG element", () => {
    const { container } = render(<IconRefresh />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconWarning renders an SVG element", () => {
    const { container } = render(<IconWarning />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("all icons have the iconSvg module class", () => {
    const icons = [IconPlay, IconSquare, IconRefresh, IconWarning];
    for (const Icon of icons) {
      const { container } = render(<Icon />);
      const svg = container.querySelector("svg");
      // CSS modules produce a scoped class name — just verify the svg has a class attribute
      expect(svg?.getAttribute("class")).toBeTruthy();
    }
  });

  it("all icons have aria-hidden='true'", () => {
    const icons = [IconPlay, IconSquare, IconRefresh, IconWarning];
    for (const Icon of icons) {
      const { container } = render(<Icon />);
      const svg = container.querySelector("svg");
      expect(svg?.getAttribute("aria-hidden")).toBe("true");
    }
  });
});
