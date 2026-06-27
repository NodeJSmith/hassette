import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { InfoPopover } from "./info-popover";

describe("InfoPopover", () => {
  it("hides the help text until the trigger is clicked", () => {
    const { getByRole, queryByTestId } = render(<InfoPopover text="Some help." label="Widget" />);
    const trigger = getByRole("button");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(queryByTestId("field-help")).toBeNull();

    fireEvent.click(trigger);

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(queryByTestId("field-help")?.textContent).toBe("Some help.");
  });

  it("toggles closed on a second click", () => {
    const { getByRole, queryByTestId } = render(<InfoPopover text="Some help." />);
    const trigger = getByRole("button");
    fireEvent.click(trigger);
    expect(queryByTestId("field-help")).not.toBeNull();
    fireEvent.click(trigger);
    expect(queryByTestId("field-help")).toBeNull();
  });

  it("closes on Escape", () => {
    const { getByRole, queryByTestId } = render(<InfoPopover text="Some help." />);
    fireEvent.click(getByRole("button"));
    expect(queryByTestId("field-help")).not.toBeNull();

    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(queryByTestId("field-help")).toBeNull();
  });

  it("closes on an outside click", () => {
    const { getByRole, queryByTestId } = render(<InfoPopover text="Some help." />);
    fireEvent.click(getByRole("button"));
    expect(queryByTestId("field-help")).not.toBeNull();

    fireEvent.pointerDown(document.body);
    expect(queryByTestId("field-help")).toBeNull();
  });
});
