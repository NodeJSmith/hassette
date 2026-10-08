import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorAlert } from "./error-alert";

describe("ErrorAlert", () => {
  it("renders the message in a danger-toned alert", () => {
    const { getByRole } = render(<ErrorAlert data-testid="err">boom</ErrorAlert>);
    const el = getByRole("alert");
    expect(el.textContent).toBe("boom");
    expect(el.dataset.testid).toBe("err");
    expect(el.className).toContain("bg-[var(--destructive-bg)]");
    expect(el.className).toContain("text-foreground");
  });
});
