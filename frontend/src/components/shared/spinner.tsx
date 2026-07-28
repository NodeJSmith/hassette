export function Spinner() {
  return (
    <div
      className="mx-auto my-4 size-6 animate-spin rounded-full border-[length:var(--border-thick)] border-[var(--border-strong)] border-t-primary"
      data-testid="spinner"
      role="status"
      aria-label="Loading"
    />
  );
}
