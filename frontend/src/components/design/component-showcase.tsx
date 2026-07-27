import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import styles from "./component-showcase.module.css";
import s from "./section.module.css";

export function ComponentShowcase() {
  return (
    <section className={s.section}>
      <h2 className={s.heading}>Components</h2>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Button</h3>
        <div className={styles.row}>
          <Button>Default</Button>
          <Button variant="default">Primary</Button>
          <Button variant="success">Success</Button>
          <Button variant="warning">Warning</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="info">Info</Button>
        </div>
        <div className={styles.row}>
          <Button size="sm">Small</Button>
          <Button size="xs">Extra Small</Button>
          <Button disabled>Disabled</Button>
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Badge</h3>
        <div className={styles.row}>
          <Badge variant="success">Running</Badge>
          <Badge variant="warning">Degraded</Badge>
          <Badge variant="danger">Failed</Badge>
          <Badge variant="neutral">Stopped</Badge>
          <Badge variant="info">Info</Badge>
        </div>
        <div className={styles.row}>
          <Badge variant="success" size="sm">
            Small
          </Badge>
          <Badge variant="success" size="xs">
            XS
          </Badge>
          <Badge variant="success" size="md">
            Medium
          </Badge>
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Badge (chip variants)</h3>
        <div className={styles.row}>
          <Badge variant="listener">Listener</Badge>
          <Badge variant="job">Job</Badge>
          <Badge variant="kind-ok">Kind</Badge>
          <Badge variant="origin">Origin</Badge>
          <Badge variant="muted">Muted</Badge>
        </div>
        <div className={styles.row}>
          <Badge variant="listener" size="sm">
            Small
          </Badge>
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>StatusShape</h3>
        <div className={styles.row}>
          <StatusShape kind="ok" />
          <StatusShape kind="warn" />
          <StatusShape kind="err" />
          <StatusShape kind="cancel" />
          <StatusShape kind="mute" />
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Card</h3>
        <div className={styles.cardGrid}>
          <Card>
            <div className={styles.cardContent}>
              <strong>Default</strong>
              <span>Standard card surface</span>
            </div>
          </Card>
          <Card variant="compact">
            <div className={styles.cardContent}>
              <strong>Compact</strong>
              <span>Reduced padding</span>
            </div>
          </Card>
          <Card variant="error">
            <div className={styles.cardContent}>
              <strong>Error</strong>
              <span>Error state card</span>
            </div>
          </Card>
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Spinner</h3>
        <div className={styles.row}>
          <Spinner />
        </div>
      </div>
    </section>
  );
}
