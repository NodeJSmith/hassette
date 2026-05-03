import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { StatusShape } from "./status-shape";

describe("StatusShape", () => {
  it("renders a filled circle for kind=ok", () => {
    const { container } = render(<StatusShape kind="ok" />);
    const circle = container.querySelector("circle");
    expect(circle).not.toBeNull();
    // Filled: no stroke or fill="none"
    expect(circle!.getAttribute("fill")).toBe("var(--ok)");
  });

  it("renders a triangle for kind=warn", () => {
    const { container } = render(<StatusShape kind="warn" />);
    const triangle = container.querySelector("polygon");
    expect(triangle).not.toBeNull();
    expect(triangle!.getAttribute("fill")).toBe("var(--warn)");
  });

  it("renders a rounded square for kind=err", () => {
    const { container } = render(<StatusShape kind="err" />);
    const rect = container.querySelector("rect");
    expect(rect).not.toBeNull();
    expect(rect!.getAttribute("fill")).toBe("var(--err)");
    // Should have rounded corners
    const rx = rect!.getAttribute("rx");
    expect(Number(rx)).toBeGreaterThan(0);
  });

  it("renders a ring (stroke-only circle) for kind=mute", () => {
    const { container } = render(<StatusShape kind="mute" />);
    const circle = container.querySelector("circle");
    expect(circle).not.toBeNull();
    expect(circle!.getAttribute("fill")).toBe("none");
    expect(circle!.getAttribute("stroke")).toBe("var(--mute)");
  });

  it("uses the default size of 12", () => {
    const { container } = render(<StatusShape kind="ok" />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("width")).toBe("12");
    expect(svg!.getAttribute("height")).toBe("12");
  });

  it("respects a custom size prop", () => {
    const { container } = render(<StatusShape kind="ok" size={20} />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("width")).toBe("20");
    expect(svg!.getAttribute("height")).toBe("20");
  });

  it("is aria-hidden to keep it decorative", () => {
    const { container } = render(<StatusShape kind="ok" />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("aria-hidden")).toBe("true");
  });

  it("uses correct color token for ok", () => {
    const { container } = render(<StatusShape kind="ok" />);
    expect(container.querySelector("circle")!.getAttribute("fill")).toBe("var(--ok)");
  });

  it("uses correct color token for warn", () => {
    const { container } = render(<StatusShape kind="warn" />);
    expect(container.querySelector("polygon")!.getAttribute("fill")).toBe("var(--warn)");
  });

  it("uses correct color token for err", () => {
    const { container } = render(<StatusShape kind="err" />);
    expect(container.querySelector("rect")!.getAttribute("fill")).toBe("var(--err)");
  });

  it("uses correct color token for mute", () => {
    const { container } = render(<StatusShape kind="mute" />);
    expect(container.querySelector("circle")!.getAttribute("stroke")).toBe("var(--mute)");
  });
});
