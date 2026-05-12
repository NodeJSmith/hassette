import styles from "./spinner.module.css";

export function Spinner() {
  return <div class={styles.spinner} data-testid="spinner" role="status" aria-label="Loading" />;
}
