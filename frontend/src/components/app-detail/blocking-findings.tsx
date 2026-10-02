import { Link } from "wouter";

import type { BlockingFinding } from "../../api/endpoints";
import { getAppBlockingFindings } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { isExecutionDefined, useAppExecution } from "../../hooks/use-scoped-execution";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppStore } from "../../state/store";
import { handlerPath, parseInstanceParam } from "../../utils/app-routes";
import { formatDuration, formatRelativeTime, pluralize } from "../../utils/format";
import { frameLabel, StackDisclosure } from "../shared/stack-frames";
import { OVERVIEW_SECTION_CLASS, SECTION_LABEL_CLASS } from "./overview-section";

const META_CLASS = "text-sm text-foreground-secondary";

/** The headline: where to look. A library call site names its package rather than posing as the fix. */
function callSiteText(finding: BlockingFinding): string {
  const site = finding.call_site;
  if (!site) return "call site not captured";
  if (!finding.call_site_is_user_code) return `detected inside ${finding.detected_in_package ?? "a library"}`;
  return frameLabel(site);
}

/** What the call site called into: the frame just inside it (Tier 1) or the intercepted primitive (Tier 2). */
function callsIntoText(finding: BlockingFinding): string | null {
  if (finding.primitive) return finding.primitive;
  if (finding.callee) return `${finding.callee.display_path} ${finding.callee.function}`;
  return null;
}

/** React key for a finding: unique within one app's findings, built from the fields that separate them. */
function findingKey(finding: BlockingFinding): string {
  const site = finding.call_site;
  const where = site ? `${site.filename}:${site.lineno}` : finding.handlers.map((h) => `${h.kind}-${h.id}`).join(",");
  return `${finding.tier}|${finding.primitive ?? ""}|${where}`;
}

function statsText(finding: BlockingFinding): string {
  const parts = [pluralize(finding.event_count, "event")];
  if (typeof finding.max_stall_ms === "number") parts.push(`up to ${formatDuration(finding.max_stall_ms)}`);
  if (typeof finding.avg_stall_ms === "number") parts.push(`avg ${formatDuration(finding.avg_stall_ms)}`);
  parts.push(`last seen ${formatRelativeTime(finding.last_seen_ts)}`);
  return parts.join(" · ");
}

interface FindingProps {
  finding: BlockingFinding;
  appKey: string;
  instanceIndex: number | undefined;
  testId: string;
}

function FindingEntry({ finding, appKey, instanceIndex, testId }: FindingProps) {
  const callsInto = callsIntoText(finding);
  const libraryLocation = finding.call_site && !finding.call_site_is_user_code ? frameLabel(finding.call_site) : null;

  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-[var(--warn)] bg-[var(--warn-bg)] p-3"
      data-testid={testId}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[length:var(--text-mono-sm)] font-medium text-foreground">
          {callSiteText(finding)}
        </span>
        {callsInto && (
          <span className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
            calls {callsInto}
          </span>
        )}
        {libraryLocation && (
          <span className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
            at {libraryLocation}
          </span>
        )}
      </div>
      {finding.handlers.length > 0 && (
        <div className={META_CLASS}>
          from{" "}
          {finding.handlers.map((h, i) => (
            <span key={`${h.kind}-${h.id}`}>
              {i > 0 && ", "}
              <Link
                href={handlerPath(appKey, h.kind, h.id, { instance: instanceIndex })}
                className="font-mono text-primary hover:underline"
              >
                {h.name}
              </Link>
            </span>
          ))}
        </div>
      )}
      <div className={META_CLASS}>{statsText(finding)}</div>
      <StackDisclosure frames={finding.latest_stack} testId={`${testId}-stack`} />
    </div>
  );
}

interface Props {
  appKey: string;
  resolvedInstanceIndex: number;
  instanceQs: string;
}

/**
 * Blocking calls this app made on the event loop, one entry per call site to fix.
 *
 * Renders nothing while loading, on a failed fetch, and when there are no findings: an empty
 * result claims nothing, since detection is best-effort.
 */
export function BlockingFindingsSection({ appKey, resolvedInstanceIndex, instanceQs }: Props) {
  const instanceIndex = parseInstanceParam(new URLSearchParams(instanceQs).get("instance"));
  const { data } = useScopedQuery(queryKeys.appBlocking.base(appKey, resolvedInstanceIndex), (since, signal) =>
    getAppBlockingFindings(appKey, resolvedInstanceIndex, since, signal),
  );
  // A blocking event is always produced by an execution, so refetch when one completes.
  const execution = useAppExecution(appKey);
  useQueryInvalidator(execution, isExecutionDefined, queryKeys.appBlocking.prefix(appKey));
  // Subscribing to tick keeps the "last seen" labels current.
  useAppStore((s) => s.tick);

  const findings = data?.findings ?? [];
  if (findings.length === 0) return null;

  return (
    <section className={OVERVIEW_SECTION_CLASS} data-testid="overview-blocking-findings">
      <h3 className={SECTION_LABEL_CLASS}>blocking calls</h3>
      <p className={META_CLASS}>
        these calls froze the event loop, delaying every other handler and timer. move them off the loop with{" "}
        <code className="font-mono">asyncio.to_thread</code>.
      </p>
      {findings.map((finding, i) => (
        <FindingEntry
          key={findingKey(finding)}
          finding={finding}
          appKey={appKey}
          instanceIndex={instanceIndex}
          testId={`overview-blocking-finding-${i}`}
        />
      ))}
      {data?.truncated && (
        <p className={META_CLASS} data-testid="overview-blocking-truncated">
          showing only the most recently seen call sites — older ones may be missing. narrow the time window to see
          them.
        </p>
      )}
    </section>
  );
}
