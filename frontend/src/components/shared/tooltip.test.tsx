import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { Tooltip } from "./tooltip";

describe("Tooltip", () => {
  it("renders children and sets data-tooltip attribute", () => {
    const { container } = render(
      <Tooltip label="avg duration"><span>23ms</span></Tooltip>,
    );
    const trigger = container.querySelector("[data-tooltip]");
    expect(trigger).not.toBeNull();
    expect(trigger!.getAttribute("data-tooltip")).toBe("avg duration");
    expect(trigger!.textContent).toBe("23ms");
  });

  it("passes through the class prop to the trigger element", () => {
    const { container } = render(
      <Tooltip label="test" class="my-custom-class"><span>val</span></Tooltip>,
    );
    const trigger = container.querySelector("[data-tooltip]");
    expect(trigger!.className).toContain("my-custom-class");
  });

  it("renders without class prop", () => {
    const { container } = render(
      <Tooltip label="test"><span>val</span></Tooltip>,
    );
    const trigger = container.querySelector("[data-tooltip]");
    expect(trigger!.className).not.toBe("");
  });

  it("does not add tabIndex by default", () => {
    const { container } = render(
      <Tooltip label="test"><span>val</span></Tooltip>,
    );
    const trigger = container.querySelector("[data-tooltip]");
    expect(trigger!.hasAttribute("tabindex")).toBe(false);
  });

  it("adds tabIndex when focusable is true", () => {
    const { container } = render(
      <Tooltip label="test" focusable><span>val</span></Tooltip>,
    );
    const trigger = container.querySelector("[data-tooltip]");
    expect(trigger!.getAttribute("tabindex")).toBe("0");
  });
});
