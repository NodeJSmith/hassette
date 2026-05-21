import type { Signal } from "@preact/signals";

import { Button } from "./button";
import styles from "./show-more-button.module.css";

interface Props {
  showAll: Signal<boolean>;
  totalCount: number;
}

export function ShowMoreButton({ showAll, totalCount }: Props) {
  return (
    <Button
      ghost
      size="xs"
      class={styles.showMore}
      onClick={() => {
        showAll.value = !showAll.value;
      }}
    >
      {showAll.value ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}
