import { useState } from "preact/hooks";
import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { StatusShape } from "../components/shared/status-shape";
import { Spinner } from "../components/shared/spinner";
import { useDocumentTitle } from "../hooks/use-document-title";
import type { StatusKind } from "../utils/status";

function Section({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <section style={{ marginBottom: "48px" }}>
      <h2 class="ht-heading-2" style={{ marginBottom: "24px", borderBottom: "2px solid var(--line-1)", paddingBottom: "8px" }}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Variant({ label, description, children }: { label: string; description: string; children: preact.ComponentChildren }) {
  return (
    <div style={{ marginBottom: "32px", padding: "20px", border: "1px solid var(--line-1)", borderRadius: "var(--r-md)", background: "var(--bg-surface)" }}>
      <div style={{ marginBottom: "12px" }}>
        <strong style={{ fontSize: "14px", color: "var(--ink-1)" }}>{label}</strong>
        <span style={{ fontSize: "12px", color: "var(--ink-3)", marginLeft: "12px" }}>{description}</span>
      </div>
      <div>{children}</div>
    </div>
  );
}

function Row({ children }: { children: preact.ComponentChildren }) {
  return <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>{children}</div>;
}

// ---- 1. Status Display ----

function StatusDisplaySection() {
  const kinds: StatusKind[] = ["ok", "warn", "err", "mute"];
  const statuses = ["running", "blocked", "failed", "disabled"];
  const badgeVariants = ["success", "warning", "danger", "neutral"];

  return (
    <Section title="1. Status Display">
      <Variant label="A — StatusShape (SVG icons)" description="Used on apps page, dashboard, handler detail. Geometric shapes, no text.">
        <Row>
          {kinds.map((k) => (
            <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <StatusShape kind={k} /> {k}
            </span>
          ))}
        </Row>
      </Variant>

      <Variant label="B — ht-badge (text pills)" description="Used on app-detail, handlers-tab, job-executions, config-tab. Colored text on tinted background.">
        <Row>
          {badgeVariants.map((v, i) => (
            <span key={v} class={`ht-badge ht-badge--${v} ht-badge--sm`}>{statuses[i]}</span>
          ))}
        </Row>
        <div style={{ marginTop: "12px" }}>
          <span style={{ fontSize: "12px", color: "var(--ink-3)", marginRight: "8px" }}>xs size:</span>
          <span class="ht-badge ht-badge--neutral ht-badge--xs">auto</span>
        </div>
        <div style={{ marginTop: "8px" }}>
          <span style={{ fontSize: "12px", color: "var(--ink-3)", marginRight: "8px" }}>with icon:</span>
          <span class="ht-badge ht-badge--danger ht-badge--sm">
            <StatusShape kind="err" size={8} /> failing
          </span>
        </div>
      </Variant>

      <Variant label="C — StatusPill (apps page only)" description="Similar to ht-badge but slightly different sizing (10px vs 11px font, px padding vs em padding).">
        <Row>
          {kinds.map((k, i) => (
            <span key={k} class={`ht-apps-status-pill ht-apps-status-pill--${k}`}>{statuses[i]}</span>
          ))}
        </Row>
      </Variant>
    </Section>
  );
}

// ---- 2. Empty States ----

function EmptyStatesSection() {
  return (
    <Section title="2. Empty States">
      <Variant label="A — ht-empty-state" description="Used on apps, handlers, dashboard. Centered muted text, 40px padding.">
        <div class="ht-empty-state">
          <p class="ht-text-muted">no items match your filter.</p>
        </div>
      </Variant>

      <Variant label="B — ht-log-empty (icon + title + body)" description="Used on log-table, config-tab, handler-invocations. Structured icon/title/body.">
        <div style={{ textAlign: "center", padding: "var(--sp-6)" }}>
          <div class="ht-log-empty__icon">∅</div>
          <div class="ht-log-empty__title">no items in window</div>
          <div class="ht-log-empty__body">nothing has been recorded recently. change the filter or extend the time window.</div>
        </div>
      </Variant>

      <Variant label="C — Ad-hoc ht-text-muted" description="Used on handlers-tab detail pane, job-executions, diagnostics. Bare inline text, no centering.">
        <p class="ht-text-muted">no handlers or scheduled jobs registered.</p>
        <p class="ht-text-muted ht-text-xs" style={{ marginTop: "8px" }}>No executions recorded. (ht-text-xs variant)</p>
      </Variant>
    </Section>
  );
}

// ---- 3. Loading States ----

function LoadingStatesSection() {
  return (
    <Section title="3. Loading States">
      <Variant label="A — Spinner component" description="Used for full-page loading on all pages. Animated spinning ring.">
        <div style={{ padding: "20px 0" }}>
          <Spinner />
        </div>
      </Variant>

      <Variant label="B — Inline text (ht-text-sm)" description="Used in config-tab, code-tab. Small muted text.">
        <span class="ht-text-muted ht-text-sm">Loading config...</span>
      </Variant>

      <Variant label="C — Inline text (ht-text-xs)" description="Used in handlers-tab. Micro-sized muted text.">
        <p class="ht-text-muted ht-text-xs">Loading invocations...</p>
      </Variant>

      <Variant label="D — Sidebar loading" description="Used in sidebar. Faintest ink color (ink-4 vs ink-3).">
        <div class="ht-sidebar__loading">Loading...</div>
      </Variant>
    </Section>
  );
}

// ---- 4. Error / Traceback Display ----

function TracebackToggle({ label }: { label: string }) {
  const open = useRef(signal(false)).current;
  return (
    <div>
      <button type="button" class="ht-btn ht-btn--sm" onClick={() => { open.value = !open.value; }} aria-expanded={open.value}>
        {open.value ? "hide traceback" : "show traceback"}
      </button>
      {open.value && (
        <pre class="ht-traceback">{`Traceback (most recent call last):\n  File "app.py", line 42, in handler\n    result = await process(event)\nValueError: ${label}`}</pre>
      )}
    </div>
  );
}

function ErrorSection() {
  return (
    <Section title="4. Error / Traceback Display">
      <Variant label="A — ErrorDisplay (white card)" description="Used on app-detail. White card surface, red text, toggle for traceback.">
        <div class="ht-card ht-mb-4">
          <p class="ht-text-danger">ValueError: invalid state transition from 'ready' to 'ready'</p>
          <div class="ht-mt-3">
            <TracebackToggle label="ErrorDisplay variant" />
          </div>
        </div>
      </Variant>

      <Variant label="B — ErrorBanner (tinted banner)" description="Used on handlers-tab detail pane. Red-tinted background with semi-transparent border.">
        <div class="ht-detail-pane__error-banner">
          <span class="ht-detail-pane__error-banner-heading">ValueError</span>
          <p class="ht-detail-pane__error-banner-message" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-micro)", color: "var(--ink-2)" }}>
            invalid state transition from 'ready' to 'ready'
          </p>
          <TracebackToggle label="ErrorBanner variant" />
        </div>
      </Variant>

      <Variant label="C — ht-alert--danger" description="Used on config page, alert banner. Solid red border, small padding.">
        <div class="ht-alert ht-alert--danger" role="alert">
          Failed to load configuration: connection refused
        </div>
      </Variant>

      <Variant label="D — ht-diag__load-error" description="Used on diagnostics page. Smaller border-radius than ht-alert.">
        <div class="ht-diag__load-error" role="alert">
          Failed to load system status: connection refused
        </div>
      </Variant>
    </Section>
  );
}

// ---- 5. Tab Strips ----

function TabStripSection() {
  const [tab1, setTab1] = useState("handlers");
  const [tab2, setTab2] = useState("handlers");

  return (
    <Section title="5. Tab Strips">
      <Variant label="A — ht-tabs (handlers page)" description="1px bottom border, gray active underline, font-weight 600.">
        <div class="ht-tabs" role="tablist" aria-label="View">
          {["handlers", "jobs"].map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab1 === t} onClick={() => setTab1(t)}>{t}</button>
          ))}
        </div>
      </Variant>

      <Variant label="B — ht-tab-strip (app-detail)" description="2px bottom border, accent active underline, font-weight 500. Supports badges.">
        <div class="ht-tab-strip" role="tablist" aria-label="Sections">
          {[{ id: "handlers", badge: 12 }, { id: "code" }, { id: "logs" }, { id: "config" }].map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab2 === t.id}
              class={`ht-tab-btn${tab2 === t.id ? " ht-tab-btn--active" : ""}`}
              onClick={() => setTab2(t.id)}
            >
              {t.id}{"badge" in t && <span class="ht-tab-btn__badge">{t.badge}</span>}
            </button>
          ))}
        </div>
      </Variant>
    </Section>
  );
}

// ---- 6. Chips / Tags ----

function ChipsSection() {
  return (
    <Section title="6. Chips / Tags">
      <Variant label="A — ht-chip (modifier + schedule)" description="Used on handlers-tab detail. Square corners (r-sm), tinted backgrounds.">
        <Row>
          <span class="ht-chip ht-chip--modifier">debounce: 500ms</span>
          <span class="ht-chip ht-chip--modifier">throttle: 1s</span>
          <span class="ht-chip ht-chip--schedule">every 5m</span>
          <span class="ht-chip ht-chip--schedule">cron: 0 */6 * * *</span>
        </Row>
      </Variant>

      <Variant label="B — ht-kind-badge" description="Used on handlers-tab detail. Pill-shaped, status-colored border + background.">
        <Row>
          {(["ok", "warn", "err", "mute"] as StatusKind[]).map((k) => (
            <span key={k} class={`ht-kind-badge ht-kind-badge--${k}`}>
              <StatusShape kind={k} size={8} /> {k === "ok" ? "listener" : k === "err" ? "failing" : k === "warn" ? "timed out" : "disabled"}
            </span>
          ))}
        </Row>
      </Variant>

      <Variant label='C — ht-badge--neutral --xs ("auto" badge)' description="Used on app-detail. Tiny pill badge.">
        <Row>
          <span class="ht-badge ht-badge--neutral ht-badge--xs">auto</span>
        </Row>
      </Variant>

      <Variant label="D — ht-apps-row__auto-badge" description="Used on apps table. 9px mono, no background fill.">
        <Row>
          <span class="ht-apps-row__auto-badge">auto</span>
        </Row>
      </Variant>

      <Variant label="E — ht-sidebar__auto-badge" description="Used on sidebar. 11px, sunken background fill.">
        <Row>
          <span class="ht-sidebar__auto-badge">auto</span>
        </Row>
      </Variant>

      <Variant label="F — ht-inv-origin-chip" description="Used on handler-invocations. 9px uppercase mono, no background.">
        <Row>
          <span class="ht-inv-origin-chip">bus</span>
          <span class="ht-inv-origin-chip">scheduler</span>
        </Row>
      </Variant>
    </Section>
  );
}

// ---- 7. Stats Strips ----

function StatsStripsSection() {
  return (
    <Section title="7. Stats Strips">
      <Variant label="A — ht-apps-stats (apps page)" description="7-column grid, 26px values, sunken background, rounded card.">
        <div class="ht-apps-stats">
          {[
            { label: "total", value: "12" },
            { label: "running", value: "8", kind: "ok" },
            { label: "blocked", value: "1", kind: "warn" },
            { label: "failed", value: "2", kind: "err" },
            { label: "disabled", value: "1", kind: "mute" },
            { label: "handlers", value: "47" },
            { label: "uptime", value: "3d 2h" },
          ].map((cell) => (
            <div key={cell.label} class="ht-apps-stats__cell">
              <span class="ht-apps-stats__label">{cell.label}</span>
              <span class={`ht-apps-stats__value${cell.kind ? ` ht-apps-stats__value--${cell.kind}` : ""}`}>{cell.value}</span>
            </div>
          ))}
        </div>
      </Variant>

      <Variant label="B — ht-overview-stats (dashboard)" description="7-column grid, 20px values, sunken background, value ABOVE label.">
        <div class="ht-overview-stats">
          {[
            { label: "uptime", value: "3d 2h" },
            { label: "apps", value: "12" },
            { label: "services", value: "8/8" },
            { label: "handlers", value: "47" },
            { label: "invocations", value: "1,234" },
            { label: "executions", value: "567" },
            { label: "dropped", value: "0" },
          ].map((cell) => (
            <div key={cell.label} class="ht-overview-stats__cell">
              <span class="ht-overview-stats__value">{cell.value}</span>
              <span class="ht-overview-stats__label">{cell.label}</span>
            </div>
          ))}
        </div>
      </Variant>

      <Variant label="C — ht-health-strip (app-detail)" description="5-column, 20px values, transparent background, bottom border separator.">
        <div class="ht-health-strip">
          {[
            { label: "handlers", value: "12" },
            { label: "ok", value: "10" },
            { label: "failing", value: "1", tone: "danger" },
            { label: "timed out", value: "1", tone: "warning" },
            { label: "jobs", value: "5" },
          ].map((cell) => (
            <div key={cell.label} class="ht-health-card">
              <span class="ht-health-card__label">{cell.label}</span>
              <span class={`ht-health-card__value${cell.tone ? ` ht-health-card__value--${cell.tone}` : ""}`}>{cell.value}</span>
            </div>
          ))}
        </div>
      </Variant>
    </Section>
  );
}

// ---- 8. Search Inputs ----

function SearchInputsSection() {
  return (
    <Section title="8. Search Inputs">
      <Variant label="A — ht-apps-search" description="12px font, 6px/10px padding, light border, min-width 160px.">
        <input type="text" class="ht-apps-search" placeholder="Search apps..." />
      </Variant>

      <Variant label="B — ht-input ht-input--sm" description="11px font, em-based padding, strong (darker) border.">
        <input type="text" class="ht-input ht-input--sm" placeholder="Search logs..." />
      </Variant>

      <Variant label="C — ht-sidebar__app-search" description="12.5px font, token padding, light border, sunken background.">
        <input type="text" class="ht-sidebar__app-search" placeholder="Filter apps..." />
      </Variant>
    </Section>
  );
}

// ---- 9. App Name Links ----

function AppNameLinksSection() {
  return (
    <Section title="9. App Name Links">
      <Variant label="A — ht-apps-row__app-name" description="Sans-serif 12.5px, weight 500, ink-1 color, hover → accent.">
        <a href="#" class="ht-apps-row__app-name" onClick={(e) => e.preventDefault()}>my_automation_app</a>
      </Variant>

      <Variant label="B — ht-overview-apps__name" description="Monospace 14px, normal weight, ink-1, hover → underline.">
        <a href="#" class="ht-overview-apps__name" onClick={(e) => e.preventDefault()}>my_automation_app</a>
      </Variant>

      <Variant label="C — ht-handlers-row__app-link" description="Inherits table font (12.5px sans), ink-1, hover → accent + underline.">
        <a href="#" class="ht-handlers-row__app-link" onClick={(e) => e.preventDefault()}>my_automation_app</a>
      </Variant>

      <Variant label="D — ht-text-mono (log table)" description="Monospace 13px, inherits link color, persistent underline.">
        <a href="#" class="ht-text-mono" onClick={(e) => e.preventDefault()}>my_automation_app</a>
      </Variant>

      <Variant label="E — ht-link (dashboard)" description="Accent color, no decoration, hover → accent-hover + underline.">
        <a href="#" class="ht-link" onClick={(e) => e.preventDefault()}>my_automation_app</a>
      </Variant>
    </Section>
  );
}

// ---- Page ----

export function PatternComparePage() {
  useDocumentTitle("Pattern Comparison");

  return (
    <div class="ht-page" style={{ maxWidth: "900px" }}>
      <div class="ht-page-header">
        <h1 class="ht-display">pattern comparison</h1>
      </div>
      <p class="ht-text-muted" style={{ marginBottom: "32px" }}>
        Side-by-side comparison of duplicated UI patterns. Each section shows the current variants — pick which one should be canonical.
      </p>

      <StatusDisplaySection />
      <EmptyStatesSection />
      <LoadingStatesSection />
      <ErrorSection />
      <TabStripSection />
      <ChipsSection />
      <StatsStripsSection />
      <SearchInputsSection />
      <AppNameLinksSection />
    </div>
  );
}
