import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BootIssue } from "../../api/endpoints";
import { BootIssuesPanel } from "./boot-issues-panel";

describe("BootIssuesPanel", () => {
  it("sorts an unrecognized severity after the known err/warn/info order", () => {
    const issues: BootIssue[] = [
      { severity: "warn", label: "Config warning", detail: "check your config" },
      // @ts-expect-error intentionally invalid severity to exercise the unknown-severity sort fallback
      { severity: "unrecognized", label: "Mystery issue", detail: "no known severity" },
      { severity: "err", label: "Critical error", detail: "failed to load something" },
      // @ts-expect-error "info" is not part of the BootIssueResponse schema but the panel's
      // SEVERITY_ORDER handles it defensively — exercise that fallback tier explicitly
      { severity: "info", label: "Informational issue", detail: "additional information" },
    ];
    const { getByTestId } = render(<BootIssuesPanel bootIssues={issues} />);

    expect(getByTestId("diag-boot-label-0").textContent).toBe("Critical error");
    expect(getByTestId("diag-boot-label-1").textContent).toBe("Config warning");
    expect(getByTestId("diag-boot-label-2").textContent).toBe("Informational issue");
    expect(getByTestId("diag-boot-label-3").textContent).toBe("Mystery issue");
  });
});
