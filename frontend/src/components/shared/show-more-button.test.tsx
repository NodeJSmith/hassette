import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ShowMoreButton } from "./show-more-button";

describe("ShowMoreButton", () => {
  it("shows 'Show all N' text when showAll is false", () => {
    const { getByRole } = render(<ShowMoreButton showAll={false} onToggle={vi.fn()} totalCount={10} />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show all 10");
  });

  it("shows 'Show less' text when showAll is true", () => {
    const { getByRole } = render(<ShowMoreButton showAll={true} onToggle={vi.fn()} totalCount={10} />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show less");
  });

  it("includes totalCount in the 'Show all' label", () => {
    const { getByRole } = render(<ShowMoreButton showAll={false} onToggle={vi.fn()} totalCount={42} />);
    expect(getByRole("button").textContent).toBe("Show all 42");
  });

  it("clicking calls onToggle", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { getByRole } = render(<ShowMoreButton showAll={false} onToggle={onToggle} totalCount={5} />);
    await user.click(getByRole("button"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("button text updates reactively after parent state flips showAll", async () => {
    const user = userEvent.setup();
    function Wrapper() {
      const [showAll, setShowAll] = useState(false);
      return <ShowMoreButton showAll={showAll} onToggle={() => setShowAll((v) => !v)} totalCount={7} />;
    }
    const { getByRole } = render(<Wrapper />);
    const button = getByRole("button");
    expect(button.textContent).toBe("Show all 7");
    await user.click(button);
    expect(button.textContent).toBe("Show less");
  });

  it("button has type='button' to avoid form submission", () => {
    const { getByRole } = render(<ShowMoreButton showAll={false} onToggle={vi.fn()} totalCount={3} />);
    expect(getByRole("button").getAttribute("type")).toBe("button");
  });
});
