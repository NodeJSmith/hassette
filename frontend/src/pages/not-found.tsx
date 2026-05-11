import { useDocumentTitle } from "../hooks/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("Not Found");
  return (
    <div class="ht-page ht-error-page">
      <h1>404</h1>
      <p class="ht-text-secondary">Page not found.</p>
      <a href="/apps" class="ht-btn ht-btn--ghost">back to apps</a>
    </div>
  );
}
