import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MergedService } from "./merge-services";
import { ServiceRow } from "./service-row";

function makeService(overrides: Partial<MergedService> = {}): MergedService {
  return {
    resource_name: "bus",
    status: "failed",
    role: "core",
    ready_phase: null,
    retry_at: null,
    exception: null,
    ...overrides,
  };
}

describe("ServiceRow", () => {
  it("does not render the exception toggle when there is no exception", () => {
    const { queryByRole } = render(<ServiceRow service={makeService({ exception: null })} />);
    expect(queryByRole("button", { name: /show exception/i })).toBeNull();
  });

  it("toggles the exception text open and closed", async () => {
    const user = userEvent.setup();
    const exception = "RuntimeError: boom";
    const { getByRole, queryByText } = render(<ServiceRow service={makeService({ exception })} />);

    expect(queryByText(exception)).toBeNull();

    const toggle = getByRole("button", { name: /show exception/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await user.click(toggle);
    expect(queryByText(exception)).not.toBeNull();
    expect(getByRole("button", { name: /hide exception/i }).getAttribute("aria-expanded")).toBe("true");

    await user.click(getByRole("button", { name: /hide exception/i }));
    expect(queryByText(exception)).toBeNull();
    expect(getByRole("button", { name: /show exception/i })).toBeDefined();
  });
});
