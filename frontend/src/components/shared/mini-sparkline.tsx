import styles from "./mini-sparkline.module.css";

export function MiniSparkline({
  buckets,
  width = 80,
  height = 20,
}: {
  buckets: Array<{ ok: number; err: number }>;
  width?: number;
  height?: number;
}) {
  if (!buckets || buckets.length < 2) return null;
  const totals = buckets.map((b) => b.ok + b.err);
  const maxVal = Math.max(...totals, 1);
  const points = buckets.map((b, i) => {
    const x = (i / (buckets.length - 1)) * width;
    const y = height - ((b.ok + b.err) / maxVal) * height;
    return { x, y, ok: b.ok, err: b.err };
  });
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const errPoints = points.filter((p) => p.err > 0);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      class={styles.sparkline}
      data-testid="mini-sparkline"
    >
      <polyline
        points={line}
        fill="none"
        stroke="var(--ok)"
        stroke-width="1.5"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      {errPoints.map((p, i) => (
        <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="2.5" fill="var(--err)">
          <title>{`${p.err} error${p.err > 1 ? "s" : ""}, ${p.ok} ok`}</title>
        </circle>
      ))}
    </svg>
  );
}
