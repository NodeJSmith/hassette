import { SMALL_ICON_SIZE } from "../../utils/constants";

interface FilterIconProps {
  size?: number;
  active?: boolean;
}

export function FilterIcon({ size = SMALL_ICON_SIZE, active = false }: FilterIconProps) {
  return (
    <span className="relative inline-flex items-center">
      <svg width={size} height={size} viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M1 2h10L7.5 6.5V10L4.5 9V6.5L1 2z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      </svg>
      {active && (
        <span
          data-testid="filter-icon-dot"
          className="absolute top-0 right-0 size-[5px] rounded-full bg-[var(--accent)]"
        />
      )}
    </span>
  );
}
