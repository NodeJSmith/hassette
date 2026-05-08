interface Props {
  appKey: string;
  instanceIndex?: number;
  query?: string;
  children?: preact.ComponentChildren;
}

export function AppLink({ appKey, instanceIndex, query, children }: Props) {
  let href = `/apps/${appKey}`;
  if (instanceIndex !== undefined) href += `/${instanceIndex}`;
  if (query) href += `?${query}`;
  return (
    <a href={href} class="ht-app-link">{children ?? appKey}</a>
  );
}
