interface Props {
  id?: string;
  source: string;
  "data-testid"?: string;
}

export function RegistrationSource({ id, source, "data-testid": testId }: Props) {
  return (
    <div id={id} className="min-w-0" data-testid={testId}>
      <pre className="m-0 whitespace-pre-wrap rounded-sm border border-border bg-card p-3 font-mono text-xs leading-[var(--text-small-leading)] [overflow-wrap:anywhere]">
        <code>{source}</code>
      </pre>
    </div>
  );
}
