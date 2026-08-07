import { useState } from "react";
import { useLocation } from "wouter";

import { Button } from "@/components/ui/button";
import { cardVariants } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { postSession } from "../api/client";
import { useDocumentTitle } from "../hooks/use-document-title";
import { HOME_PATH } from "../utils/app-routes";

const PAGE_CLASS = "flex min-h-screen flex-1 flex-col items-center justify-center gap-6 p-8";
// The card surface comes from the shared primitive rather than a hand-copied class list, so
// theme changes to Card reach the login view too. The element stays a <form>, which is why
// cardVariants() is composed here instead of rendering <Card>.
const CARD_CLASS = cn(cardVariants(), "flex w-full max-w-sm flex-col gap-4 p-6");
const TITLE_CLASS = "m-0 font-heading text-[length:var(--text-display)] font-normal text-foreground";
const LABEL_CLASS = "text-sm font-medium text-foreground-secondary";
const INPUT_CLASS =
  "w-full rounded-md border border-[var(--line-1)] bg-[var(--bg-sunken)] px-3 py-2 text-sm text-[var(--ink-1)] outline-none transition-colors placeholder:text-[var(--ink-4)] focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]";
const ALERT_CLASS =
  "flex items-start gap-3 rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-foreground";

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
          <div className={ALERT_CLASS} role="alert" data-testid="login-error">
            {error}
          </div>
        )}
        <Button type="submit" disabled={submitting || token.length === 0}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
