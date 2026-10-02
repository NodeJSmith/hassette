import type { UnattributedBlockingData, UnattributedStall } from "../../api/endpoints";
import { formatDuration, formatRelativeTime, formatTimestamp, pluralize } from "../../utils/format";
import { frameLabel, StackDisclosure } from "../shared/stack-frames";
import { Panel } from "./panel";

const META_CLASS = "text-sm text-foreground-secondary";

function summaryText(data: UnattributedBlockingData): string {
  const parts = [`${data.displaced_count} displaced`, `${data.framework_count} framework`];
  if (typeof data.max_stall_ms === "number") parts.push(`longest ${formatDuration(data.max_stall_ms)}`);
  return `${pluralize(data.total_count, "stall")}: ${parts.join(" · ")}`;
}

function StallRow({ stall, index }: { stall: UnattributedStall; index: number }) {
  const what =
    stall.primitive ??
    (typeof stall.stall_duration_ms === "number" ? formatDuration(stall.stall_duration_ms) : "stall");
  return (
    <li
      className="flex flex-col gap-1 border-t border-border pt-3 first:border-t-0 first:pt-0"
      data-testid={`diag-stall-${index}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className="font-mono text-[length:var(--text-mono-sm)] text-foreground"
          title={formatTimestamp(stall.detected_ts)}
        >
          {formatRelativeTime(stall.detected_ts)}
        </span>
        <span className="font-mono text-[length:var(--text-mono-sm)] font-medium text-foreground">{what}</span>
        <span className={META_CLASS}>{stall.reason}</span>
        {stall.app_frame && (
          <span className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
            app code in stack: {frameLabel(stall.app_frame)}
          </span>
        )}
      </div>
      <StackDisclosure frames={stall.stack} testId={`diag-stall-${index}-stack`} />
    </li>
  );
}

interface Props {
  data: UnattributedBlockingData;
}

/**
 * Loop stalls no app is credited with. A displaced stall had an app execution in flight, but a
 * different task held the loop, so attribution was withheld rather than guessed; a framework stall
 * had no app execution responsible at all. App code seen in a stack is shown as evidence only.
 */
export function LoopStallsPanel({ data }: Props) {
  return (
    <Panel title="loop stalls" ariaLabel="Unattributed loop stalls" data-testid="diag-loop-stalls-panel">
      <p className={META_CLASS} data-testid="diag-loop-stalls-summary">
        {summaryText(data)}
      </p>
      <p className={META_CLASS}>
        none of these are credited to an app. <strong>displaced</strong> — an app was running, but a different task held
        the loop, so blame was withheld. <strong>framework</strong> — no app execution was responsible.
      </p>
      <ul className="flex list-none flex-col gap-3 p-0" aria-label="Recent loop stalls">
        {data.recent.map((stall, i) => (
          <StallRow key={`${stall.detected_ts}-${i}`} stall={stall} index={i} />
        ))}
      </ul>
      {data.truncated && <p className={META_CLASS}>showing only the most recent stalls — counts are partial.</p>}
    </Panel>
  );
}
