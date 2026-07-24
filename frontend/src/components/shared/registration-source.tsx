import styles from "./registration-source.module.css";

interface Props {
  id?: string;
  source: string;
  "data-testid"?: string;
}

export function RegistrationSource({ id, source, "data-testid": testId }: Props) {
  return (
    <div id={id} class={styles.wrapper} data-testid={testId}>
      <pre class={styles.codeSnippet}>
        <code>{source}</code>
      </pre>
    </div>
  );
}
