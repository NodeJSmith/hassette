import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import {
  IconLayers,
  IconBell,
  IconClock,
  IconScroll,
  IconPlay,
  IconSquare,
  IconRefresh,
  IconWarning,
  IconInfo,
  IconCheck,
  IconDashboard,
  IconBoxes,
  IconHistory,
  IconScrollText,
} from "./icons";

describe("Icons smoke tests", () => {
  it("IconLayers renders an SVG element", () => {
    const { container } = render(<IconLayers />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconBell renders an SVG element", () => {
    const { container } = render(<IconBell />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconClock renders an SVG element", () => {
    const { container } = render(<IconClock />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconScroll renders an SVG element", () => {
    const { container } = render(<IconScroll />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

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

  it("IconInfo renders an SVG element", () => {
    const { container } = render(<IconInfo />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconCheck renders an SVG element", () => {
    const { container } = render(<IconCheck />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconDashboard renders an SVG element", () => {
    const { container } = render(<IconDashboard />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconBoxes renders an SVG element", () => {
    const { container } = render(<IconBoxes />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconHistory renders an SVG element", () => {
    const { container } = render(<IconHistory />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("IconScrollText renders an SVG element", () => {
    const { container } = render(<IconScrollText />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("all icons have the ht-icon-svg class", () => {
    const icons = [
      IconLayers, IconBell, IconClock, IconScroll, IconPlay, IconSquare,
      IconRefresh, IconWarning, IconInfo, IconCheck, IconDashboard, IconBoxes,
      IconHistory, IconScrollText,
    ];
    for (const Icon of icons) {
      const { container } = render(<Icon />);
      const svg = container.querySelector("svg");
      // SVG elements in JSDOM use SVGAnimatedString for className; use getAttribute
      expect(svg?.getAttribute("class")).toContain("ht-icon-svg");
    }
  });

  it("all icons have aria-hidden='true'", () => {
    const icons = [
      IconLayers, IconBell, IconClock, IconScroll, IconPlay, IconSquare,
      IconRefresh, IconWarning, IconInfo, IconCheck, IconDashboard, IconBoxes,
      IconHistory, IconScrollText,
    ];
    for (const Icon of icons) {
      const { container } = render(<Icon />);
      const svg = container.querySelector("svg");
      expect(svg?.getAttribute("aria-hidden")).toBe("true");
    }
  });
});
