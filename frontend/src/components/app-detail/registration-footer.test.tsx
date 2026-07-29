import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RegistrationFooter } from "./registration-footer";

describe("RegistrationFooter", () => {
  it("renders nothing when no sourceLocation and no registrationSource", () => {
    const { container } = render(<RegistrationFooter kind="handler" testId="handler-detail-1" />);
    expect(container.innerHTML).toBe("");
  });

  it("shows source location when provided", () => {
    const { getByTestId } = render(
      <RegistrationFooter kind="handler" testId="handler-detail-1" sourceLocation="apps/foo.py:12" />,
    );
    expect(getByTestId("handler-source-location")).not.toBeNull();
  });

  it("shows view-in-code button when onViewCode and sourceLocation are provided", async () => {
    const user = userEvent.setup();
    const onViewCode = vi.fn();
    const { getByTestId } = render(
      <RegistrationFooter
        kind="handler"
        testId="handler-detail-1"
        sourceLocation="apps/foo.py:12"
        onViewCode={onViewCode}
      />,
    );
    const btn = getByTestId("view-in-code-btn");
    await user.click(btn);
    expect(onViewCode).toHaveBeenCalledWith(12);
  });

  it("hides view-in-code button when onViewCode is not provided", () => {
    const { queryByTestId } = render(
      <RegistrationFooter kind="handler" testId="handler-detail-1" sourceLocation="apps/foo.py:12" />,
    );
    expect(queryByTestId("view-in-code-btn")).toBeNull();
  });

  it("toggles registration source visibility on button click", async () => {
    const user = userEvent.setup();
    const { getByTestId, queryByTestId } = render(
      <RegistrationFooter kind="job" testId="job-detail-42" registrationSource="scheduler.run_in(foo, 5)" />,
    );
    const toggle = getByTestId("job-registration-toggle");
    expect(toggle.textContent).toContain("show call");
    expect(queryByTestId("job-registration-source")).toBeNull();

    await user.click(toggle);
    expect(toggle.textContent).toContain("hide call");
    expect(getByTestId("job-registration-source")).not.toBeNull();

    await user.click(toggle);
    expect(toggle.textContent).toContain("show call");
    expect(queryByTestId("job-registration-source")).toBeNull();
  });
});
