import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { FilterIcon } from "./filter-icon";

describe("FilterIcon", () => {
  it("renders an SVG element", () => {
    const { container } = render(<FilterIcon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("renders the funnel path", () => {
    const { container } = render(<FilterIcon />);
    const path = container.querySelector("path");
    expect(path).not.toBeNull();
  });

  it("defaults to size 12", () => {
    const { container } = render(<FilterIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("12");
    expect(svg?.getAttribute("height")).toBe("12");
  });

  it("accepts a custom size prop", () => {
    const { container } = render(<FilterIcon size={16} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("16");
    expect(svg?.getAttribute("height")).toBe("16");
  });

  it("marks SVG as aria-hidden", () => {
    const { container } = render(<FilterIcon />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
  });

  it("shows active dot when active=true", () => {
    render(<FilterIcon active={true} />);
    const dot = screen.getByTestId("filter-icon-dot");
    expect(dot).toBeTruthy();
  });

  it("does not show active dot when active=false", () => {
    render(<FilterIcon active={false} />);
    expect(screen.queryByTestId("filter-icon-dot")).toBeNull();
  });

  it("does not show active dot when active is omitted", () => {
    render(<FilterIcon />);
    expect(screen.queryByTestId("filter-icon-dot")).toBeNull();
  });
});
