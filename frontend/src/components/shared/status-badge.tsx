interface Props {
  status: string;
  size?: "small" | "";
}

export function StatusBadge({ status, size = "" }: Props) {
  const sizeClass = size === "small" ? " ht-status-badge-sm" : "";
  return (
    <span class={`ht-status-badge ht-status-${status}${sizeClass}`}>
      <span class="ht-status-dot" />
      <span class="ht-status-label">{status}</span>
    </span>
  );
}
