import { useAppState } from "../../state/context";
import { setStoredValue } from "../../utils/local-storage";
import type { SessionScope } from "../../utils/session-scope";

const SCOPES: readonly { value: SessionScope; label: string }[] = [
  { value: "current", label: "This Session" },
  { value: "all", label: "All Time" },
] as const;

export function SessionScopeToggle() {
  const { sessionScope } = useAppState();
  const active = sessionScope.value;

  const setScope = (next: SessionScope) => {
    if (next === active) return;
    sessionScope.value = next;
    setStoredValue("sessionScope", next);
  };

  return (
    <div class="ht-scope-toggle" role="group" aria-label="Telemetry time scope" data-testid="scope-toggle">
      {SCOPES.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          class={`ht-scope-toggle__btn${value === active ? " is-active" : ""}`}
          aria-pressed={value === active}
          data-testid={`scope-${value}`}
          onClick={() => setScope(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
