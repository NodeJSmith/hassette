import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { ErrorCell } from "./error-cell";

describe("ErrorCell", () => {
  it("renders dash when no traceback and no message", () => {
    const { container } = render(
      <ErrorCell traceback={null} message={null} expanded={false} onToggle={vi.fn()} />,
    );
    expect(container.textContent).toBe("—");
  });

  it("renders message when no traceback", () => {
    const { container } = render(
      <ErrorCell traceback={null} message="No such entity" expanded={false} onToggle={vi.fn()} />,
    );
    expect(container.textContent).toBe("No such entity");
  });

  it("renders message and traceback toggle button when traceback is present", () => {
    const { getByText, getByRole } = render(
      <ErrorCell
        traceback="Traceback..."
        message="Something failed"
        expanded={false}
        onToggle={vi.fn()}
      />,
    );
    expect(getByText("Something failed")).toBeDefined();
    const btn = getByRole("button", { name: /show traceback/i });
    expect(btn).toBeDefined();
    expect(btn.textContent).toBe("Traceback");
  });

  it("button label reflects expanded state — shows 'Hide traceback' when expanded", () => {
    const { getByRole } = render(
      <ErrorCell
        traceback="Traceback..."
        message="Error"
        expanded={true}
        onToggle={vi.fn()}
      />,
    );
    const btn = getByRole("button", { name: /hide traceback/i });
    expect(btn).toBeDefined();
    expect(btn.textContent).toBe("Hide traceback");
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("button has aria-expanded=false when collapsed", () => {
    const { getByRole } = render(
      <ErrorCell
        traceback="Traceback..."
        message="Error"
        expanded={false}
        onToggle={vi.fn()}
      />,
    );
    const btn = getByRole("button");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("calls onToggle when button is clicked", () => {
    const onToggle = vi.fn();
    const { getByRole } = render(
      <ErrorCell
        traceback="Traceback..."
        message="Error"
        expanded={false}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(getByRole("button"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("falls back to 'Error' label when message is null but traceback is present", () => {
    const { getByText } = render(
      <ErrorCell
        traceback="Traceback..."
        message={null}
        expanded={false}
        onToggle={vi.fn()}
      />,
    );
    expect(getByText("Error")).toBeDefined();
  });
});
