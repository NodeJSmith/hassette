import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import {
  designGroupClassName,
  designGroupLabelClassName,
  designHeadingClassName,
  designSectionClassName,
} from "./design-showcase";

const rowClassName = "flex flex-wrap items-center gap-2";
const cardContentClassName =
  "flex flex-col gap-1 p-4 font-sans text-sm text-foreground-secondary [&_strong]:text-[length:var(--text-body)] [&_strong]:font-semibold [&_strong]:text-foreground";

export function ComponentShowcase() {
  return (
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Components</h2>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Button</h3>
        <div className={rowClassName}>
          <Button>Default</Button>
          <Button variant="default">Primary</Button>
          <Button variant="success">Success</Button>
          <Button variant="warning">Warning</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="info">Info</Button>
        </div>
        <div className={rowClassName}>
          <Button size="sm">Small</Button>
          <Button size="xs">Extra Small</Button>
          <Button disabled>Disabled</Button>
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Badge</h3>
        <div className={rowClassName}>
          <Badge variant="success">Running</Badge>
          <Badge variant="warning">Degraded</Badge>
          <Badge variant="danger">Failed</Badge>
          <Badge variant="neutral">Stopped</Badge>
          <Badge variant="info">Info</Badge>
        </div>
        <div className={rowClassName}>
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

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Badge (chip variants)</h3>
        <div className={rowClassName}>
          <Badge variant="listener">Listener</Badge>
          <Badge variant="job">Job</Badge>
          <Badge variant="kind-ok">Kind</Badge>
          <Badge variant="origin">Origin</Badge>
          <Badge variant="muted">Muted</Badge>
        </div>
        <div className={rowClassName}>
          <Badge variant="listener" size="sm">
            Small
          </Badge>
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>StatusShape</h3>
        <div className={rowClassName}>
          <StatusShape kind="ok" />
          <StatusShape kind="warn" />
          <StatusShape kind="err" />
          <StatusShape kind="cancel" />
          <StatusShape kind="mute" />
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Card</h3>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
          <Card>
            <div className={cardContentClassName}>
              <strong>Default</strong>
              <span>Standard card surface</span>
            </div>
          </Card>
          <Card variant="compact">
            <div className={cardContentClassName}>
              <strong>Compact</strong>
              <span>Reduced padding</span>
            </div>
          </Card>
          <Card variant="error">
            <div className={cardContentClassName}>
              <strong>Error</strong>
              <span>Error state card</span>
            </div>
          </Card>
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Spinner</h3>
        <div className={rowClassName}>
          <Spinner />
        </div>
      </div>
    </section>
  );
}
