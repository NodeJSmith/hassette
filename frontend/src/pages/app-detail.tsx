interface Props {
  params: { key: string };
}

export function AppDetailPage({ params }: Props) {
  return (
    <div>
      <h1>App: {params.key}</h1>
      <p class="ht-text-secondary">Health strip, handlers, jobs, logs — coming in WP05.</p>
    </div>
  );
}
