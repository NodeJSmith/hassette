import { cn } from "@/lib/utils";

import { parseSourceLocation } from "../../utils/format";

interface Props {
  sourceLocation: string;
  "data-testid"?: string;
}

export function SourceLocation({ sourceLocation, "data-testid": testId }: Props) {
  const { filename, line } = parseSourceLocation(sourceLocation);

  return (
    <div className="inline-flex items-center" data-testid={testId}>
      <span className={cn("font-mono text-sm text-muted-foreground")}>
        {filename}
        {line ? `:${line}` : ""}
      </span>
    </div>
  );
}
