import { Badge } from "@/components/ui/badge";

export function HandlerModeChip({ mode }: { mode: string }) {
  return (
    <Badge variant="muted" data-testid="handler-mode-chip">
      mode: {mode}
    </Badge>
  );
}
