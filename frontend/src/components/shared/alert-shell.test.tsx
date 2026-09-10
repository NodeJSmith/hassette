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

  it("applies tone-specific background tokens", () => {
    const { getByTestId: getDanger } = render(
      <AlertShell tone="danger" data-testid="danger">
        x
      </AlertShell>,
    );
    const { getByTestId: getWarning } = render(
      <AlertShell tone="warning" data-testid="warning">
        x
      </AlertShell>,
    );
    expect(getDanger("danger").className).toContain("bg-[var(--destructive-bg)]");
    expect(getWarning("warning").className).toContain("bg-[var(--status-warning-bg)]");
  });

  it("lets className override the shell's own geometry", () => {
    // The className contract promises twMerge ordering, so a conflicting utility wins. Pinned
    // because `panel.tsx`'s PANEL_BANNER_CLASS relies on it to drop the standalone bottom margin.
    const { getByTestId } = render(
      <AlertShell tone="warning" className="mb-0 rounded-sm" data-testid="b">
        nested
      </AlertShell>,
    );
    const el = getByTestId("b");
    expect(el.className).toContain("mb-0");
    expect(el.className).not.toContain("mb-4");
    expect(el.className).toContain("rounded-sm");
    expect(el.className).not.toContain("rounded-md");
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
