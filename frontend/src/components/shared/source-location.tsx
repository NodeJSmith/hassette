import { parseSourceLocation } from "../../utils/format";
import styles from "./source-location.module.css";

interface Props {
  sourceLocation: string;
  "data-testid"?: string;
}

export function SourceLocation({ sourceLocation, "data-testid": testId }: Props) {
  const { filename, line } = parseSourceLocation(sourceLocation);

  return (
    <div class={styles.wrapper} data-testid={testId}>
      <span class="ht-text-mono ht-text-sm ht-text-muted">
        {filename}
        {line ? `:${line}` : ""}
      </span>
    </div>
  );
}
