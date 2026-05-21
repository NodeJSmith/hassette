import { useDocumentTitle } from "../hooks/use-document-title";
import styles from "./not-found.module.css";

export function NotFoundPage() {
  useDocumentTitle("Not Found");
  return (
    <div class={`ht-page ${styles.page}`} data-testid="not-found-page">
      <h1>404</h1>
      <p class="ht-text-secondary">Page not found.</p>
      <a href="/apps" class={styles.backLink}>
        back to apps
      </a>
    </div>
  );
}
