import { useEffect } from "preact/hooks";

export function NotFoundPage() {
  useEffect(() => { document.title = "Not Found - Hassette"; }, []);
  return (
    <div class="ht-error-page">
      <h1>404</h1>
      <p class="ht-text-secondary">Page not found.</p>
      <a href="/" class="ht-btn ht-btn--primary">Back to Dashboard</a>
    </div>
  );
}
