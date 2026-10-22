import { useAppStore } from "@/state/store";

/**
 * The log views' one opt-in: framework lines at ERROR and above always show, and this adds the
 * rest of Hassette's lines. One persisted preference, so every log view shows the same thing.
 */
export function FrameworkLinesToggle() {
  const checked = useAppStore((s) => s.showAllFrameworkLogs);
  const setChecked = useAppStore((s) => s.setShowAllFrameworkLogs);

  return (
    <label
      className="flex cursor-pointer items-center gap-1.5 text-xs whitespace-nowrap select-none"
      title="Hassette's own errors always show. Turn this on to also see its debug, info and warning lines."
    >
      <input
        type="checkbox"
        className="accent-primary"
        checked={checked}
        onChange={(e) => setChecked(e.currentTarget.checked)}
        data-testid="framework-lines-toggle"
      />
      all framework lines
    </label>
  );
}
