import { Link } from "wouter";

import styles from "./app-link.module.css";

interface Props {
  appKey: string;
  instanceIndex?: number;
  handlerId?: string;
  children?: preact.ComponentChildren;
}

export function AppLink({ appKey, instanceIndex, handlerId, children }: Props) {
  let path = `/apps/${appKey}`;
  if (handlerId !== undefined) path += `/handlers/${handlerId}`;

  const params = new URLSearchParams();
  if (instanceIndex !== undefined) params.set("instance", String(instanceIndex));

  const search = params.toString();
  const href = search ? `${path}?${search}` : path;

  return (
    <Link href={href} class={styles.link}>
      {children ?? appKey}
    </Link>
  );
}
