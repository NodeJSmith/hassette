import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { Spinner } from "./spinner";

describe("Spinner", () => {
  it("renders without crashing", () => {
    const { container } = render(<Spinner />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the spinner element with ht-spinner class", () => {
    const { container } = render(<Spinner />);
    expect(container.querySelector(".ht-spinner")).not.toBeNull();
  });

  it("has role='status' for screen reader accessibility", () => {
    const { getByRole } = render(<Spinner />);
    expect(getByRole("status")).toBeDefined();
  });

  it("has accessible aria-label", () => {
    const { getByLabelText } = render(<Spinner />);
    expect(getByLabelText("Loading")).toBeDefined();
  });
});
