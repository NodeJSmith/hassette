import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BootIssue } from "../../api/endpoints";
import { BootIssuesPanel } from "./boot-issues-panel";

describe("BootIssuesPanel", () => {
  it("sorts an unrecognized severity after the known err/warn/info order", () => {
    const issues: BootIssue[] = [
      { severity: "warn", label: "Config warning", detail: "check your config" },
      { severity: "unrecognized" as BootIssue["severity"], label: "Mystery issue", detail: "no known severity" },
      { severity: "err", label: "Critical error", detail: "failed to load something" },
    ];
    const { getByTestId } = render(<BootIssuesPanel bootIssues={issues} />);

    expect(getByTestId("diag-boot-label-0").textContent).toBe("Critical error");
    expect(getByTestId("diag-boot-label-1").textContent).toBe("Config warning");
    expect(getByTestId("diag-boot-label-2").textContent).toBe("Mystery issue");
  });
});
