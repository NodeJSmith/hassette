interface FilterIconProps {
  size?: number;
  active?: boolean;
}

export function FilterIcon({ size = 12, active = false }: FilterIconProps) {
  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      <svg width={size} height={size} viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M1 2h10L7.5 6.5V10L4.5 9V6.5L1 2z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
      </svg>
      {active && (
        <span
          data-testid="filter-icon-dot"
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: "5px",
            height: "5px",
            borderRadius: "50%",
            background: "var(--accent)",
          }}
        />
      )}
    </span>
  );
}
