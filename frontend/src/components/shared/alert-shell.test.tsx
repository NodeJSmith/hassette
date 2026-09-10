import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertShell } from "./alert-shell";

describe("AlertShell", () => {
  it("renders children inside the shared shell", () => {
    const { getByTestId } = render(
      <AlertShell tone="danger" data-testid="b">
        boom
      </AlertShell>,
    );
    const el = getByTestId("b");
    expect(el.textContent).toBe("boom");
    expect(el.className).toContain("rounded-md");
  });

  it("applies the danger background token", () => {
    const { getByTestId } = render(
      <AlertShell tone="danger" data-testid="b">
        x
      </AlertShell>,
    );
    expect(getByTestId("b").className).toContain("bg-[var(--destructive-bg)]");
  });

  it("applies the warning background token", () => {
    const { getByTestId } = render(
      <AlertShell tone="warning" data-testid="b">
        x
      </AlertShell>,
    );
    expect(getByTestId("b").className).toContain("bg-[var(--status-warning-bg)]");
  });

  it("forwards role and extra classes", () => {
    const { getByTestId } = render(
      <AlertShell tone="warning" role="alert" className="text-[var(--status-warning)]" data-testid="b">
        blocked
      </AlertShell>,
    );
    const el = getByTestId("b");
    expect(el.getAttribute("role")).toBe("alert");
    expect(el.className).toContain("text-[var(--status-warning)]");
  });
});
