import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { ErrorDisplay } from "./error-display";

describe("ErrorDisplay", () => {
  it("renders the error message", () => {
    const { getByText } = render(
      <ErrorDisplay errorMessage="Something broke" errorTraceback={null} />,
    );
    expect(getByText("Something broke")).toBeDefined();
  });

  it("does not render traceback button when errorTraceback is null", () => {
    const { queryByRole } = render(
      <ErrorDisplay errorMessage="Something broke" errorTraceback={null} />,
    );
    expect(queryByRole("button")).toBeNull();
  });

  it("renders traceback toggle button when errorTraceback is provided", () => {
    const { getByRole } = render(
      <ErrorDisplay
        errorMessage="Something broke"
        errorTraceback="Traceback (most recent call last):\n  File test.py, line 1"
      />,
    );
    const btn = getByRole("button");
    expect(btn.textContent).toContain("Show traceback");
  });

  it("traceback is hidden initially", () => {
    const { container } = render(
      <ErrorDisplay
        errorMessage="Something broke"
        errorTraceback="Traceback..."
      />,
    );
    expect(container.querySelector("pre.ht-traceback")).toBeNull();
  });

  it("clicking 'Show traceback' reveals the traceback pre element", () => {
    const tracebackText = "Traceback (most recent call last):\n  File test.py, line 1";
    const { getByRole, container } = render(
      <ErrorDisplay
        errorMessage="Something broke"
        errorTraceback={tracebackText}
      />,
    );

    fireEvent.click(getByRole("button"));

    const pre = container.querySelector("pre.ht-traceback");
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain("Traceback (most recent call last)");
  });

  it("clicking 'Hide traceback' after expand hides the traceback again", () => {
    const { getByRole, container } = render(
      <ErrorDisplay
        errorMessage="Err"
        errorTraceback="Traceback..."
      />,
    );

    fireEvent.click(getByRole("button")); // show
    expect(container.querySelector("pre.ht-traceback")).not.toBeNull();

    fireEvent.click(getByRole("button")); // hide
    expect(container.querySelector("pre.ht-traceback")).toBeNull();
  });

  it("button toggles aria-expanded attribute", () => {
    const { getByRole } = render(
      <ErrorDisplay errorMessage="Err" errorTraceback="Traceback..." />,
    );
    const btn = getByRole("button");
    expect(btn.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("button text changes from 'Show traceback' to 'Hide traceback' after expand", () => {
    const { getByRole } = render(
      <ErrorDisplay errorMessage="Err" errorTraceback="Traceback..." />,
    );
    const btn = getByRole("button");
    expect(btn.textContent).toBe("Show traceback");

    fireEvent.click(btn);
    expect(btn.textContent).toBe("Hide traceback");
  });
});
