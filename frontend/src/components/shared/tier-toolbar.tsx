interface TierToolbarProps {
  tierFilter: "all" | "app" | "framework";
  onTierChange: (tier: "all" | "app" | "framework") => void;
  appKeys?: string[];
  selectedApp?: string;
  onAppChange?: (app: string) => void;
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  testIdPrefix: string;
}

export function TierToolbar({
  tierFilter,
  onTierChange,
  appKeys,
  selectedApp = "",
  onAppChange,
  search = "",
  onSearchChange,
  searchPlaceholder = "Search...",
  testIdPrefix,
}: TierToolbarProps) {
  const appLabel = selectedApp ? `app: ${selectedApp}` : "app: all";

  return (
    <div class="ht-tier-toolbar">
      <div class="ht-tier-toggle" data-testid={`${testIdPrefix}-tier-toggle`}>
        {(["all", "app", "framework"] as const).map((t) => (
          <button
            key={t}
            type="button"
            class={`ht-tier-toggle__btn${tierFilter === t ? " ht-tier-toggle__btn--active" : ""}`}
            onClick={() => { onTierChange(t); }}
          >
            {t === "all" ? "All" : t === "app" ? "Apps" : "Framework"}
          </button>
        ))}
      </div>
      {appKeys && appKeys.length > 0 && onAppChange && (
        <label class="ht-pill ht-pill--mute ht-pill--interactive">
          {appLabel}
          <select
            class="ht-pill__select"
            aria-label="Filter by app"
            value={selectedApp}
            onChange={(e) => onAppChange((e.target as HTMLSelectElement).value)}
            data-testid={`${testIdPrefix}-app-filter`}
          >
            <option value="">all apps</option>
            {appKeys.map((key) => (
              <option key={key} value={key}>{key}</option>
            ))}
          </select>
        </label>
      )}
      {onSearchChange && (
        <input
          class="ht-search"
          type="text"
          aria-label="Search"
          placeholder={searchPlaceholder}
          value={search}
          onInput={(e) => { onSearchChange((e.target as HTMLInputElement).value); }}
        />
      )}
    </div>
  );
}
