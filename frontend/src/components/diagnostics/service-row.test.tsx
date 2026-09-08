import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MergedService } from "./merge-services";
import { ServiceRow } from "./service-row";

const SHOW_EXCEPTION = { name: /show exception/i } as const;
const HIDE_EXCEPTION = { name: /hide exception/i } as const;

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
    expect(queryByRole("button", SHOW_EXCEPTION)).toBeNull();
  });

  it("toggles the exception text open and closed", async () => {
    const user = userEvent.setup();
    const exception = "RuntimeError: boom";
    const { getByRole, queryByText } = render(<ServiceRow service={makeService({ exception })} />);

    expect(queryByText(exception)).toBeNull();

    const toggle = getByRole("button", SHOW_EXCEPTION);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await user.click(toggle);
    expect(queryByText(exception)).not.toBeNull();
    // Re-querying by the flipped name is itself the assertion that the accessible name changed.
    expect(getByRole("button", HIDE_EXCEPTION).getAttribute("aria-expanded")).toBe("true");

    await user.click(toggle);
    expect(queryByText(exception)).toBeNull();
    expect(getByRole("button", SHOW_EXCEPTION).getAttribute("aria-expanded")).toBe("false");
  });
});
