import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./empty-state";

describe("EmptyState", () => {
  it("renders title and default icon", () => {
    render(<EmptyState title="No items found" />);
    expect(screen.getByText("No items found")).toBeTruthy();
    expect(screen.getByText("∅")).toBeTruthy();
  });

  it("renders custom icon", () => {
    render(<EmptyState icon="🔍" title="Search" />);
    expect(screen.getByText("🔍")).toBeTruthy();
  });

  it("renders body text when provided", () => {
    render(<EmptyState title="Empty" body="Try adjusting your filters." />);
    expect(screen.getByText("Try adjusting your filters.")).toBeTruthy();
  });

  it("renders children", () => {
    render(
      <EmptyState title="Empty">
        <button type="button">Reset</button>
      </EmptyState>,
    );
    expect(screen.getByRole("button", { name: "Reset" })).toBeTruthy();
  });

  it("applies data-testid", () => {
    render(<EmptyState title="Empty" data-testid="custom-empty" />);
    expect(screen.getByTestId("custom-empty")).toBeTruthy();
  });
});
