import type { BootIssue } from "../../api/endpoints";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { StatusShape } from "../shared/status-shape";
import { Panel } from "./panel";

const SEVERITY_ORDER: Record<string, number> = { err: 0, warn: 1, info: 2 };
const UNKNOWN_SEVERITY_SORT_ORDER = 99;

interface BootIssuesPanelProps {
  bootIssues: BootIssue[];
}

export function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  const sorted = [...bootIssues].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER) -
      (SEVERITY_ORDER[b.severity] ?? UNKNOWN_SEVERITY_SORT_ORDER),
  );

  return (
    <Panel title="boot issues" ariaLabel="Boot issues" data-testid="diag-boot-panel">
      <ul className="flex list-none flex-col gap-3 p-0" aria-label="Boot issues">
        {sorted.map((issue, i) => (
          <li
            key={`${i}-${issue.severity}-${issue.label}`}
            className="flex items-start gap-3"
            data-testid={`diag-boot-issue-${i}`}
          >
            <StatusShape kind={issue.severity === "err" ? "err" : "warn"} size={STATUS_DOT_SIZE} />
            <div className="flex flex-1 flex-col gap-1">
              <span
                className="text-[length:var(--text-body)] font-medium text-foreground"
                data-testid={`diag-boot-label-${i}`}
              >
                {issue.label}
              </span>
              <span className="text-sm text-foreground-secondary" data-testid={`diag-boot-detail-${i}`}>
                {issue.detail}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
