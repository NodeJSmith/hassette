import { Link } from "wouter";

import type { BlockingFinding } from "../../api/endpoints";
import { getAppBlockingFindings } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { isExecutionDefined, useAppExecution } from "../../hooks/use-scoped-execution";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppStore } from "../../state/store";
import { handlerPath } from "../../utils/app-routes";
import { formatDuration, formatRelativeTime, pluralize } from "../../utils/format";
import { META_CLASS, MONO_META_CLASS, MONO_STRONG_CLASS } from "../shared/blocking-styles";
import { frameLabel, StackDisclosure } from "../shared/stack-frames";
import { OVERVIEW_SECTION_CLASS, SECTION_LABEL_CLASS } from "./overview-section";

const FINDING_CARD_CLASS = "flex flex-col gap-1.5 rounded-md border border-[var(--warn)] bg-[var(--warn-bg)] p-3";

/**
 * Which findings a section shows. `app` is the multi-instance parent overview: every instance, each
 * finding naming its instances. `instance` is one instance's overview; `linkInstance` is the page's
 * `?instance=` value carried onto handler links (absent on a single-instance app's page).
 */
export type BlockingScope = { kind: "app" } | { kind: "instance"; index: number; linkInstance: number | undefined };

function instanceLabel(inst: BlockingFinding["instances"][number]): string {
  return inst.name ?? `instance ${inst.index}`;
}

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

/**
 * React key for a finding: unique within one response. Instance is not part of it because the
 * server merges each call site across instances, and handler ids are already per instance.
 */
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
  scope: BlockingScope;
  testId: string;
}

function FindingEntry({ finding, appKey, scope, testId }: FindingProps) {
  const acrossInstances = scope.kind === "app";
  const instanceName = (index: number) => {
    const inst = finding.instances.find((i) => i.index === index);
    return inst ? instanceLabel(inst) : `instance ${index}`;
  };
  const callsInto = callsIntoText(finding);
  const libraryLocation = finding.call_site && !finding.call_site_is_user_code ? frameLabel(finding.call_site) : null;

  return (
    <div className={FINDING_CARD_CLASS} data-testid={testId}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className={MONO_STRONG_CLASS}>{callSiteText(finding)}</span>
        {callsInto && <span className={MONO_META_CLASS}>calls {callsInto}</span>}
        {libraryLocation && <span className={MONO_META_CLASS}>at {libraryLocation}</span>}
      </div>
      {finding.handlers.length > 0 && (
        <div className={META_CLASS}>
          from{" "}
          {finding.handlers.map((h, i) => (
            <span key={`${h.kind}-${h.id}`}>
              {i > 0 && ", "}
              <Link
                href={handlerPath(appKey, h.kind, h.id, {
                  instance: scope.kind === "app" ? h.instance_index : scope.linkInstance,
                })}
                className="font-mono text-primary hover:underline"
              >
                {h.name}
              </Link>
              {acrossInstances && ` (${instanceName(h.instance_index)})`}
            </span>
          ))}
        </div>
      )}
      {acrossInstances && (
        <div className={META_CLASS} data-testid={`${testId}-instances`}>
          on {finding.instances.map(instanceLabel).join(", ")}
        </div>
      )}
      <div className={META_CLASS}>{statsText(finding)}</div>
      <StackDisclosure frames={finding.latest_stack} testId={`${testId}-stack`} />
    </div>
  );
}

interface Props {
  appKey: string;
  scope: BlockingScope;
}

/**
 * Blocking calls this app made on the event loop, one entry per call site to fix.
 *
 * Renders nothing while loading, on a failed fetch, and when there are no findings: an empty
 * result claims nothing, since detection is best-effort.
 */
export function BlockingFindingsSection({ appKey, scope }: Props) {
  const instanceIndex = scope.kind === "instance" ? scope.index : undefined;
  const { data } = useScopedQuery(queryKeys.appBlocking.base(appKey, instanceIndex), (since, signal) =>
    getAppBlockingFindings(appKey, instanceIndex, since, signal),
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
      <h3 className={SECTION_LABEL_CLASS}>blocking calls{scope.kind === "app" && " · all instances"}</h3>
      <p className={META_CLASS}>
        these calls froze the event loop, delaying every other handler and timer. move them off the loop with{" "}
        <code className="font-mono">asyncio.to_thread</code>.
      </p>
      {findings.map((finding, i) => (
        <FindingEntry
          key={findingKey(finding)}
          finding={finding}
          appKey={appKey}
          scope={scope}
          testId={`overview-blocking-finding-${i}`}
        />
      ))}
      {data?.truncated && (
        <p className={META_CLASS} data-testid="overview-blocking-truncated">
          showing only the most recently seen call sites — older ones are omitted. narrow the time window to see them.
        </p>
      )}
    </section>
  );
}
