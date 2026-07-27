import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./error-boundary";

// A component that throws unconditionally — used to trigger error boundary.
// The return type annotation satisfies React's JSX type checking even though
// the function always throws (never actually returns).
function Bomb({ message }: { message: string }): null {
  throw new Error(message);
}

// A component that renders normally
function SafeChild() {
  return <div data-testid="safe-child">Content OK</div>;
}

// Render a Bomb inside ErrorBoundary, silencing the React console.error noise.
// React emits console.error for every caught render error — this is expected.
function renderWithError(message: string) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const result = render(
    <ErrorBoundary>
      <Bomb message={message} />
    </ErrorBoundary>,
  );
  errorSpy.mockRestore();
  return result;
}

describe("ErrorBoundary — safe children", () => {
  it("renders children when no error is thrown", () => {
    const { getByTestId } = render(
      <ErrorBoundary>
        <SafeChild />
      </ErrorBoundary>,
    );
    expect(getByTestId("safe-child")).toBeDefined();
  });

  it("renders multiple children without wrapping element", () => {
    const { container } = render(
      <ErrorBoundary>
        <p>child one</p>
        <p>child two</p>
      </ErrorBoundary>,
    );
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });
});

describe("ErrorBoundary — error fallback", () => {
  it("renders 'Something went wrong' heading when child throws", () => {
    const { getByText } = renderWithError("boom");
    expect(getByText("Something went wrong")).toBeDefined();
  });

  it("displays the thrown error message in the fallback", () => {
    const { getByText } = renderWithError("detailed error text");
    expect(getByText("detailed error text")).toBeDefined();
  });

  it("renders a Retry button in the fallback", () => {
    const { getByRole } = renderWithError("fail");
    expect(getByRole("button", { name: /retry/i })).toBeDefined();
  });

  it("renders error card container in the fallback", () => {
    const { getByTestId } = renderWithError("card error");
    expect(getByTestId("error-card")).toBeDefined();
  });

  it("does not propagate the error to the caller", () => {
    // If the boundary re-threw, this expect block would itself throw
    expect(() => renderWithError("contained")).not.toThrow();
  });
});

describe("ErrorBoundary — Retry button", () => {
  it("clicking Retry resets the boundary to the non-error state", () => {
    // Use a module-level flag (not a render counter) so the throw decision is stable across
    // React 19's internal synchronous-recovery retry — React re-invokes a component that threw
    // during a concurrent render pass a second time, in the same initial `render()` call, to
    // distinguish real errors from transient concurrent-mode inconsistencies. A counter-based
    // condition would flip to "recovered" during that internal retry, before the fallback UI
    // (and its Retry button) ever becomes visible to the test.
    let shouldThrow = true;

    function MaybeThrow() {
      if (shouldThrow) {
        throw new Error("first render");
      }
      return <div data-testid="recovered">recovered</div>;
    }

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { getByRole, getByTestId } = render(
      <ErrorBoundary>
        <MaybeThrow />
      </ErrorBoundary>,
    );
    errorSpy.mockRestore();

    // Error state is showing
    const retryBtn = getByRole("button", { name: /retry/i });

    // Simulate the underlying condition being fixed, then click Retry — boundary resets,
    // child re-renders without throwing.
    shouldThrow = false;
    const errorSpy2 = vi.spyOn(console, "error").mockImplementation(() => {});
    fireEvent.click(retryBtn);
    errorSpy2.mockRestore();

    expect(getByTestId("recovered")).toBeDefined();
  });
});
