import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertBanner } from "./alert-banner";

describe("AlertBanner", () => {
  it("renders children inside the shared shell", () => {
    const { getByTestId } = render(
      <AlertBanner tone="danger" data-testid="b">
        boom
      </AlertBanner>,
    );
    const el = getByTestId("b");
    expect(el.textContent).toBe("boom");
    expect(el.className).toContain("rounded-md");
  });

  it("applies tone-specific background tokens", () => {
    const { getByTestId: getDanger } = render(
      <AlertBanner tone="danger" data-testid="danger">
        x
      </AlertBanner>,
    );
    const { getByTestId: getWarning } = render(
      <AlertBanner tone="warning" data-testid="warning">
        x
      </AlertBanner>,
    );
    expect(getDanger("danger").className).toContain("bg-[var(--destructive-bg)]");
    expect(getWarning("warning").className).toContain("bg-[var(--status-warning-bg)]");
  });

  it("forwards role and extra classes", () => {
    const { getByTestId } = render(
      <AlertBanner tone="warning" role="alert" className="text-[var(--status-warning)]" data-testid="b">
        blocked
      </AlertBanner>,
    );
    const el = getByTestId("b");
    expect(el.getAttribute("role")).toBe("alert");
    expect(el.className).toContain("text-[var(--status-warning)]");
  });
});
