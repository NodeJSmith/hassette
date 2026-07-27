import { Button } from "@/components/ui/button";

import styles from "./show-more-button.module.css";

interface Props {
  showAll: boolean;
  onToggle: () => void;
  totalCount: number;
}

export function ShowMoreButton({ showAll, onToggle, totalCount }: Props) {
  return (
    <Button variant="ghost" size="xs" className={styles.showMore} onClick={onToggle}>
      {showAll ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}
