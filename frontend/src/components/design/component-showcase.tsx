import { Badge } from "../shared/badge";
import { Button } from "../shared/button";
import { Card } from "../shared/card";
import { Chip } from "../shared/chip";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import styles from "./component-showcase.module.css";
import s from "./section.module.css";

export function ComponentShowcase() {
  return (
    <section class={s.section}>
      <h2 class={s.heading}>Components</h2>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Button</h3>
        <div class={styles.row}>
          <Button>Default</Button>
          <Button variant="primary">Primary</Button>
          <Button variant="success">Success</Button>
          <Button variant="warning">Warning</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="info">Info</Button>
        </div>
        <div class={styles.row}>
          <Button size="sm">Small</Button>
          <Button size="xs">Extra Small</Button>
          <Button disabled>Disabled</Button>
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Badge</h3>
        <div class={styles.row}>
          <Badge variant="success">Running</Badge>
          <Badge variant="warning">Degraded</Badge>
          <Badge variant="danger">Failed</Badge>
          <Badge variant="neutral">Stopped</Badge>
          <Badge variant="info">Info</Badge>
        </div>
        <div class={styles.row}>
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

      <div class={s.group}>
        <h3 class={s.groupLabel}>Chip</h3>
        <div class={styles.row}>
          <Chip variant="modifier">Modifier</Chip>
          <Chip variant="schedule">Schedule</Chip>
          <Chip variant="kind" kind="ok">
            Kind
          </Chip>
          <Chip variant="origin">Origin</Chip>
          <Chip variant="muted">Muted</Chip>
        </div>
        <div class={styles.row}>
          <Chip variant="modifier" size="sm">
            Small
          </Chip>
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>StatusShape</h3>
        <div class={styles.row}>
          <StatusShape kind="ok" />
          <StatusShape kind="warn" />
          <StatusShape kind="err" />
          <StatusShape kind="cancel" />
          <StatusShape kind="mute" />
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Card</h3>
        <div class={styles.cardGrid}>
          <Card>
            <div class={styles.cardContent}>
              <strong>Default</strong>
              <span>Standard card surface</span>
            </div>
          </Card>
          <Card variant="compact">
            <div class={styles.cardContent}>
              <strong>Compact</strong>
              <span>Reduced padding</span>
            </div>
          </Card>
          <Card variant="error">
            <div class={styles.cardContent}>
              <strong>Error</strong>
              <span>Error state card</span>
            </div>
          </Card>
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Spinner</h3>
        <div class={styles.row}>
          <Spinner />
        </div>
      </div>
    </section>
  );
}
