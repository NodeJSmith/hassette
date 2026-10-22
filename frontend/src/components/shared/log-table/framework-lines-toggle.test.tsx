import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAppStore } from "@/state/store";

import { FrameworkLinesToggle } from "./framework-lines-toggle";

describe("FrameworkLinesToggle", () => {
  it("starts unchecked and turns on the shared preference", () => {
    const { getByTestId } = render(<FrameworkLinesToggle />);
    const checkbox = getByTestId("framework-lines-toggle") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    fireEvent.click(checkbox);

    expect(useAppStore.getState().showAllFrameworkLogs).toBe(true);
    expect(checkbox.checked).toBe(true);
  });

  it("reflects a preference set elsewhere", () => {
    useAppStore.getState().setShowAllFrameworkLogs(true);
    const { getByTestId } = render(<FrameworkLinesToggle />);
    expect((getByTestId("framework-lines-toggle") as HTMLInputElement).checked).toBe(true);
  });
});
