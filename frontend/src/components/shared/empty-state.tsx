interface Props {
  icon?: string;
  title: string;
  body?: string;
  "data-testid"?: string;
  children?: preact.ComponentChildren;
}

export function EmptyState({ icon = "∅", title, body, "data-testid": testId, children }: Props) {
  return (
    <div class="ht-empty" data-testid={testId}>
      {icon && <div class="ht-empty__icon">{icon}</div>}
      <div class="ht-empty__title">{title}</div>
      {body && <div class="ht-empty__body">{body}</div>}
      {children}
    </div>
  );
}
