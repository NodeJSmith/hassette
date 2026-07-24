import { Chip } from "../shared/chip";

export function HandlerModeChip({ mode }: { mode: string }) {
  return (
    <Chip variant="schedule" data-testid="handler-mode-chip">
      mode: {mode}
    </Chip>
  );
}
