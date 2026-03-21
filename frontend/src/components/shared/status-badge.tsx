interface Props {
  status: string;
  size?: "small" | "";
  blockReason?: string;
}

const VARIANT_MAP: Record<string, string> = {
  running: "running",
  failed: "failed",
  stopped: "stopped",
  disabled: "disabled",
  blocked: "disabled",
};

const BADGE_VARIANT_MAP: Record<string, string> = {
  running: "success",
  failed: "danger",
  stopped: "warning",
  blocked: "warning",
  disabled: "neutral",
};

export function StatusBadge({ status, size = "", blockReason }: Props) {
  if (size === "small") {
    const variant = BADGE_VARIANT_MAP[status] ?? "neutral";
    return (
      <span class={`ht-badge ht-badge--sm ht-badge--${variant}`} title={blockReason}>
        {status}
      </span>
    );
  }

  const variant = VARIANT_MAP[status] ?? "neutral";
  return (
    <span class={`ht-status-badge ht-status-badge--${variant}`} title={blockReason}>
      <span class="ht-status-badge__dot" />
      <span class="ht-status-badge__label">{status}</span>
    </span>
  );
}
