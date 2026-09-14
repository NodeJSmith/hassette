import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import { designHeadingClassName, designSectionClassName, ShowcaseGroup } from "./design-showcase";

const rowClassName = "flex flex-wrap items-center gap-2";
const cardContentClassName =
  "flex flex-col gap-1 p-4 font-sans text-sm text-foreground-secondary [&_strong]:text-[length:var(--text-body)] [&_strong]:font-semibold [&_strong]:text-foreground";

export function ComponentShowcase() {
  return (
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Components</h2>

      <ShowcaseGroup label="Button">
        <div className={rowClassName}>
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">Link</Button>
          <Button variant="destructive">Destructive</Button>
        </div>
        <div className={rowClassName}>
          <Button variant="success">Success</Button>
          <Button variant="warning">Warning</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="info">Info</Button>
        </div>
        <div className={rowClassName}>
          <Button variant="success-ghost">Success Ghost</Button>
          <Button variant="warning-ghost">Warning Ghost</Button>
          <Button variant="info-ghost">Info Ghost</Button>
        </div>
        <div className={rowClassName}>
          <Button size="sm">Small</Button>
          <Button size="xs">Extra Small</Button>
          <Button disabled>Disabled</Button>
        </div>
      </ShowcaseGroup>

      <ShowcaseGroup label="Badge">
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
      </ShowcaseGroup>

      <ShowcaseGroup label="Badge (chip variants)">
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
      </ShowcaseGroup>

      <ShowcaseGroup label="StatusShape">
        <div className={rowClassName}>
          <StatusShape kind="ok" />
          <StatusShape kind="warn" />
          <StatusShape kind="err" />
          <StatusShape kind="cancel" />
          <StatusShape kind="mute" />
        </div>
      </ShowcaseGroup>

      <ShowcaseGroup label="Card">
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
      </ShowcaseGroup>

      <ShowcaseGroup label="Spinner">
        <div className={rowClassName}>
          <Spinner />
        </div>
      </ShowcaseGroup>
    </section>
  );
}
