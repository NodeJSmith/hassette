import { describe, expect, it } from "vitest";

import { renderWithAppState } from "../test/render-helpers";
import { DesignPage } from "./design";

describe("DesignPage", () => {
  it("renders the page heading", () => {
    const { getByRole } = renderWithAppState(<DesignPage />);
    expect(getByRole("heading", { name: /design system/i })).toBeDefined();
  });

  it("renders all four token sections", () => {
    const { getByRole } = renderWithAppState(<DesignPage />);
    expect(getByRole("heading", { name: /color palette/i })).toBeDefined();
    expect(getByRole("heading", { name: /typography/i })).toBeDefined();
    expect(getByRole("heading", { name: /spacing, radii & shadows/i })).toBeDefined();
    expect(getByRole("heading", { name: /components/i })).toBeDefined();
  });
});
