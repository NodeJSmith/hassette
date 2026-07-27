import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DetailHeader } from "./detail-header";

describe("DetailHeader", () => {
  it("renders the handler name in a heading", () => {
    const { getByRole } = render(
      <DetailHeader name="kitchen_light_listener" kindLabel="listener" statusKind="ok" kind="handler" />,
    );
    expect(getByRole("heading", { level: 2 }).textContent).toBe("kitchen_light_listener");
  });

  it("shows the failing badge when statusKind is 'err'", () => {
    const { getByTestId } = render(
      <DetailHeader name="broken_listener" kindLabel="listener" statusKind="err" kind="handler" />,
    );
    expect(getByTestId("handler-status-pill").textContent).toBe("failing");
  });

  it("hides the failing badge when statusKind is 'ok'", () => {
    const { queryByTestId } = render(
      <DetailHeader name="healthy_listener" kindLabel="listener" statusKind="ok" kind="handler" />,
    );
    expect(queryByTestId("handler-status-pill")).toBeNull();
  });

  it("renders the kind chip with the correct label", () => {
    const { getByLabelText } = render(<DetailHeader name="my_job" kindLabel="cron" statusKind="ok" kind="job" />);
    const chip = getByLabelText("kind: cron");
    expect(chip.textContent).toContain("cron");
  });

  it("renders the subtitle when provided", () => {
    const { getByTestId } = render(
      <DetailHeader name="my_job" kindLabel="cron" statusKind="ok" kind="job" subtitle="runs every hour" />,
    );
    expect(getByTestId("job-human-description").textContent).toBe("runs every hour");
  });

  it("does not render a subtitle description when not provided", () => {
    const { queryByTestId } = render(<DetailHeader name="my_job" kindLabel="cron" statusKind="ok" kind="job" />);
    expect(queryByTestId("job-human-description")).toBeNull();
  });

  it("renders header actions when provided", () => {
    const { getByTestId } = render(
      <DetailHeader
        name="my_listener"
        kindLabel="listener"
        statusKind="ok"
        kind="handler"
        headerActions={<button data-testid="run-now-btn">run now</button>}
      />,
    );
    expect(getByTestId("run-now-btn")).not.toBeNull();
  });
});
