import { Link } from "wouter";

import { useDocumentTitle } from "../hooks/use-document-title";
import { HOME_PATH } from "../utils/app-routes";

export function NotFoundPage() {
  useDocumentTitle("Not Found");
  return (
    <div
      className="flex flex-1 flex-col gap-8 p-[var(--spacing-18)] text-center max-mobile:p-3 max-small-mobile:p-2"
      data-testid="not-found-page"
    >
      <h1>404</h1>
      <p className="text-foreground-secondary">Page not found.</p>
      <Link href={HOME_PATH} className="text-primary hover:underline">
        back to apps
      </Link>
    </div>
  );
}
