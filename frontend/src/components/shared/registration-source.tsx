import styles from "./registration-source.module.css";

interface Props {
  source: string;
  "data-testid"?: string;
}

export function RegistrationSource({ source, "data-testid": testId }: Props) {
  return (
    <div class={styles.wrapper} data-testid={testId}>
      <span class="ht-detail-label">Registration</span>
      <pre class={styles.codeSnippet}><code>{source}</code></pre>
    </div>
  );
}
