const LISTENER_PREFIX = "h";
const JOB_PREFIX = "j";

const HANDLER_ID_RE = /^([hj])-(\d+)$/;

export function formatListenerId(id: number): string {
  return `${LISTENER_PREFIX}-${id}`;
}

export function formatJobId(id: number): string {
  return `${JOB_PREFIX}-${id}`;
}

export function parseHandlerId(encoded: string): { kind: "listener" | "job"; id: number } | null {
  const match = HANDLER_ID_RE.exec(encoded);
  if (!match) return null;
  const id = parseInt(match[2], 10);
  if (match[1] === LISTENER_PREFIX) return { kind: "listener", id };
  if (match[1] === JOB_PREFIX) return { kind: "job", id };
  return null;
}
