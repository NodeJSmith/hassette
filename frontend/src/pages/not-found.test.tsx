import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { NotFoundPage } from "./not-found";

describe("NotFoundPage", () => {
  it("renders 404 heading", () => {
    const { getByRole } = render(<NotFoundPage />);
    expect(getByRole("heading", { name: "404" })).toBeDefined();
  });

  it("renders 'Page not found.' message", () => {
    const { getByText } = render(<NotFoundPage />);
    expect(getByText("Page not found.")).toBeDefined();
  });

  it("renders a link back to dashboard", () => {
    const { getByRole } = render(<NotFoundPage />);
    const link = getByRole("link", { name: /back to dashboard/i });
    expect(link.getAttribute("href")).toBe("/");
  });

  it("renders within the ht-error-page container", () => {
    const { container } = render(<NotFoundPage />);
    expect(container.querySelector(".ht-error-page")).not.toBeNull();
  });
});
