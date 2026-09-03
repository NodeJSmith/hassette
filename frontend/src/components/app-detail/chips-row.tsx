import type { ComponentProps } from "react";

import { Badge } from "@/components/ui/badge";

import { HandlerModeChip } from "./handler-mode-chip";

export interface Chip {
  label: string;
  value?: string;
}

export function ChipsRow({
  mode,
  variant,
  testId,
  chips,
}: {
  mode: ComponentProps<typeof HandlerModeChip>["mode"];
  variant: ComponentProps<typeof Badge>["variant"];
  testId: string;
  chips: Chip[];
}) {
  return (
    <div className="mb-3 flex flex-wrap gap-2" data-testid={testId}>
      <HandlerModeChip mode={mode} />
      {chips.map((chip) => (
        <Badge key={chip.label} variant={variant}>
          {chip.label}
          {chip.value ? ` ${chip.value}` : ""}
        </Badge>
      ))}
    </div>
  );
}
