import { Link } from "wouter";

import { useDocumentTitle } from "../hooks/use-document-title";
import { HOME_PATH } from "../utils/app-routes";
import styles from "./not-found.module.css";

export function NotFoundPage() {
  useDocumentTitle("Not Found");
  return (
    <div className={`ht-page ${styles.page}`} data-testid="not-found-page">
      <h1>404</h1>
      <p className="ht-text-secondary">Page not found.</p>
      <Link href={HOME_PATH} className={styles.backLink}>
        back to apps
      </Link>
    </div>
  );
}
