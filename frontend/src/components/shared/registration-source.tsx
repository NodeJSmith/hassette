import styles from "./registration-source.module.css";

interface Props {
  id?: string;
  source: string;
  "data-testid"?: string;
}

export function RegistrationSource({ id, source, "data-testid": testId }: Props) {
  return (
    <div id={id} className={styles.wrapper} data-testid={testId}>
      <pre className={styles.codeSnippet}>
        <code>{source}</code>
      </pre>
    </div>
  );
}
