import { describe, expect, it } from "vitest";
import { render, fireEvent, act } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { ShowMoreButton } from "./show-more-button";

describe("ShowMoreButton", () => {
  it("shows 'Show all N' text when showAll is false", () => {
    const showAll = signal(false);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={10} />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show all 10");
  });

  it("shows 'Show less' text when showAll is true", () => {
    const showAll = signal(true);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={10} />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show less");
  });

  it("includes totalCount in the 'Show all' label", () => {
    const showAll = signal(false);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={42} />);
    expect(getByRole("button").textContent).toBe("Show all 42");
  });

  it("clicking toggles showAll signal from false to true", () => {
    const showAll = signal(false);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={5} />);
    act(() => {
      fireEvent.click(getByRole("button"));
    });
    expect(showAll.value).toBe(true);
  });

  it("clicking toggles showAll signal from true to false", () => {
    const showAll = signal(true);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={5} />);
    act(() => {
      fireEvent.click(getByRole("button"));
    });
    expect(showAll.value).toBe(false);
  });

  it("button text updates reactively after click", () => {
    const showAll = signal(false);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={7} />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show all 7");
    act(() => {
      fireEvent.click(button);
    });
    expect(button.textContent).toBe("Show less");
  });

  it("button has type='button' to avoid form submission", () => {
    const showAll = signal(false);
    const { getByRole } = render(<ShowMoreButton showAll={showAll} totalCount={3} />);
    expect(getByRole("button").getAttribute("type")).toBe("button");
  });
});
