import { Button } from "./button";
import styles from "./show-more-button.module.css";

interface Props {
  showAll: boolean;
  onToggle: () => void;
  totalCount: number;
}

export function ShowMoreButton({ showAll, onToggle, totalCount }: Props) {
  return (
    <Button ghost size="xs" className={styles.showMore} onClick={onToggle}>
      {showAll ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}
