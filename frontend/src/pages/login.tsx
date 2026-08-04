import { useState } from "react";
import { useLocation } from "wouter";

import { postSession } from "../api/client";
import { useDocumentTitle } from "../hooks/use-document-title";
import { HOME_PATH } from "../utils/app-routes";

const PAGE_CLASS = "flex min-h-screen flex-1 flex-col items-center justify-center gap-6 p-8";
const CARD_CLASS = "flex w-full max-w-sm flex-col gap-4 rounded-md border border-border bg-card p-6 shadow-sm";
const TITLE_CLASS = "m-0 font-heading text-[length:var(--text-display)] font-normal text-foreground";
const LABEL_CLASS = "text-sm font-medium text-foreground-secondary";
const INPUT_CLASS =
  "w-full rounded-md border border-[var(--line-1)] bg-[var(--bg-sunken)] px-3 py-2 text-sm text-[var(--ink-1)] outline-none transition-colors placeholder:text-[var(--ink-4)] focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]";
const ERROR_CLASS = "rounded-md border border-destructive bg-[var(--destructive-bg)] px-3 py-2 text-sm text-foreground";
// A native <button> rather than the shadcn Button primitive — Button hardcodes type="button"
// (see components/ui/button.tsx), which would break native Enter-to-submit behavior on the
// only <form> in this codebase.
const SUBMIT_CLASS =
  "inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50";

export function LoginPage() {
  useDocumentTitle("Log in");
  const [, navigate] = useLocation();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    setError(null);
    setSubmitting(true);
    const result = await postSession(token);
    setSubmitting(false);

    if (result.ok) {
      navigate(HOME_PATH);
    } else {
      setError(result.message);
    }
  }

  return (
    <div className={PAGE_CLASS} data-testid="login-page">
      <form className={CARD_CLASS} onSubmit={(e) => void handleSubmit(e)}>
        <h1 className={TITLE_CLASS}>log in</h1>
        <p className="text-sm text-foreground-secondary">
          Paste the token from the hassette startup log (or <code>docker logs</code> output).
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor="login-token" className={LABEL_CLASS}>
            Token
          </label>
          <input
            id="login-token"
            type="password"
            autoComplete="current-password"
            className={INPUT_CLASS}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            data-testid="login-token-input"
            required
          />
        </div>
        {error && (
          <div className={ERROR_CLASS} role="alert" data-testid="login-error">
            {error}
          </div>
        )}
        <button type="submit" className={SUBMIT_CLASS} disabled={submitting || token.length === 0}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
