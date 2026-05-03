import { useEffect } from "preact/hooks";

export function ConfigPage() {
  useEffect(() => { document.title = "Config - Hassette"; }, []);
  return (
    <div class="ht-section">
      <h1>Config</h1>
      <p class="ht-text-muted">Configuration settings coming soon.</p>
    </div>
  );
}
