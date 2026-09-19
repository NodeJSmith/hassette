import type { BootIssue } from "../../api/endpoints";
import { STATUS_SHAPE_SIZE } from "../../utils/constants";
import { StatusShape } from "../shared/status-shape";
import { Panel } from "./panel";

// Keyed by the severity union rather than `string` so a severity added to the response schema
// fails type checking here instead of silently sorting last.
const SEVERITY_ORDER: Record<BootIssue["severity"], number> = { err: 0, warn: 1 };

interface BootIssuesPanelProps {
  bootIssues: BootIssue[];
}

export function BootIssuesPanel({ bootIssues }: BootIssuesPanelProps) {
  const sorted = [...bootIssues].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);

  return (
    <Panel title="boot issues" ariaLabel="Boot issues" data-testid="diag-boot-panel">
      <ul className="flex list-none flex-col gap-3 p-0" aria-label="Boot issue list">
        {sorted.map((issue, i) => (
          <li
            key={`${i}-${issue.severity}-${issue.label}`}
            className="flex items-start gap-3"
            data-testid={`diag-boot-issue-${i}`}
          >
            <StatusShape kind={issue.severity} size={STATUS_SHAPE_SIZE} />
            <div className="flex flex-1 flex-col gap-1">
              <span className="font-medium text-foreground" data-testid={`diag-boot-label-${i}`}>
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
