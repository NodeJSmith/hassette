import { statusToVariant } from "../../utils/status";

interface Props {
  status: string;
  size?: "small" | "";
  blockReason?: string;
}

export function StatusBadge({ status, size = "", blockReason }: Props) {
  const variant = statusToVariant(status);

  if (size === "small") {
    return (
      <span class={`ht-badge ht-badge--sm ht-badge--${variant}`} title={blockReason}>
        {status}
      </span>
    );
  }

  return (
    <span class={`ht-status-badge ht-status-badge--${variant}`} title={blockReason}>
      <span class="ht-status-badge__dot" />
      <span class="ht-status-badge__label">{status}</span>
    </span>
  );
}
