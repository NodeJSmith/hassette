import { render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { NotFoundPage } from "./not-found";

vi.mock("wouter", () => ({
  Link: (props: Record<string, unknown>) => <a {...props} />,
}));

describe("NotFoundPage", () => {
  it("renders 404 heading", () => {
    const { getByRole } = render(<NotFoundPage />);
    expect(getByRole("heading", { name: "404" })).toBeDefined();
  });

  it("renders 'Page not found.' message", () => {
    const { getByText } = render(<NotFoundPage />);
    expect(getByText("Page not found.")).toBeDefined();
  });

  it("renders a link back to apps", () => {
    const { getByRole } = render(<NotFoundPage />);
    const link = getByRole("link", { name: /back to apps/i });
    expect(link.getAttribute("href")).toBe("/apps");
  });

  it("renders within the page container", () => {
    const { getByTestId } = render(<NotFoundPage />);
    expect(getByTestId("not-found-page")).toBeDefined();
  });
});
