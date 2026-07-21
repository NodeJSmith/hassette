import { Link } from "wouter";

import { appDetailPath, type HandlerKind, handlerPath } from "../../utils/app-routes";
import styles from "./app-link.module.css";

interface Props {
  appKey: string;
  instanceIndex?: number;
  handlerKind?: HandlerKind;
  handlerId?: number;
  children?: preact.ComponentChildren;
}

export function AppLink({ appKey, instanceIndex, handlerKind, handlerId, children }: Props) {
  const query = instanceIndex !== undefined ? { instance: instanceIndex } : undefined;
  const href =
    handlerKind !== undefined && handlerId !== undefined
      ? handlerPath(appKey, handlerKind, handlerId, query)
      : appDetailPath(appKey, undefined, query);

  return (
    <Link href={href} class={styles.link}>
      {children ?? appKey}
    </Link>
  );
}
