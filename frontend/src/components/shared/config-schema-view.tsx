/**
 * Shared, read-only config renderer driven by a JSON schema + values pair.
 *
 * Renders both the global Config page (HassetteConfig) and the per-app Config tab
 * through a single component. The schema must be fully deref'd (no $ref) — the
 * server resolves all references before sending.
 *
 * Grouping: one section per nested-object field, ordered by ui.order then declaration
 * order. Flat (scalar) fields at the top level collect under a "general" section.
 *
 * Labels: ui.label when set, otherwise the humanized field name. Help text from
 * schema description. Group titles from ui.group_label, otherwise humanized key.
 *
 * Secret detection: mirrors backend _is_secret_node — checks writeOnly/format:password
 * on the node and inside anyOf branches (covers the SecretStr | None pattern).
 * The value is already masked server-side; the schema marker controls the visual style.
 *
 * ui.tier is part of the namespace shape but is unset on all fields and ignored here —
 * no show-advanced affordance is built.
 */

import clsx from "clsx";
import { useState } from "preact/hooks";

import type { ConfigRecord, SchemaNode, UiHints } from "../../api/config-view-types";
import { Badge } from "./badge";
import { Card } from "./card";
import styles from "./config-schema-view.module.css";
import { EmptyState } from "./empty-state";

interface ConfigSchemaViewProps {
  /** Fully deref'd JSON schema (no $ref). */
  schema: SchemaNode;
  /** Masked values dict. Secrets are already masked server-side. */
  values: ConfigRecord;
  /** Message when the config has no fields at all. */
  emptyMessage?: string;
}

const ACRONYM_DISPLAY: Record<string, string> = {
  url: "URL",
  api: "API",
  ha: "HA",
  ssl: "SSL",
  id: "ID",
  io: "I/O",
  cors: "CORS",
  ui: "UI",
  toml: "TOML",
};

/** Convert snake_case to Title Case, expanding known acronyms. */
function humanizeKey(key: string): string {
  return key
    .split("_")
    .map((word) => {
      const acronym = ACRONYM_DISPLAY[word.toLowerCase()];
      if (acronym) return acronym;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

/**
 * Return true when the schema node represents a secret-typed field.
 * Mirrors backend _is_secret_node in web/config_view.py.
 */
function isSecretNode(node: SchemaNode): boolean {
  if (node.writeOnly === true || node.format === "password") return true;
  if (node.anyOf) {
    for (const branch of node.anyOf) {
      if (branch.writeOnly === true || branch.format === "password") return true;
    }
  }
  return false;
}

/** Return true when this schema node represents a nested config group (object). */
function isGroupNode(node: SchemaNode): boolean {
  if (node.type === "object" && node.properties !== null && node.properties !== undefined) return true;
  // Also handle anyOf with an object branch (e.g. optional nested group).
  if (node.anyOf) {
    for (const branch of node.anyOf) {
      if (branch.type === "object" && branch.properties !== null && branch.properties !== undefined) return true;
    }
  }
  return false;
}

/**
 * Extract the effective SchemaNode for display from a node that may wrap its
 * real type inside anyOf (e.g. SecretStr | None or SomeModel | None).
 */
function unwrapAnyOf(node: SchemaNode): SchemaNode {
  if (!node.anyOf || node.anyOf.length === 0) return node;
  // Take the first non-null branch as the representative type.
  const nonNull = node.anyOf.find((b) => b.type !== "null");
  return nonNull ?? node;
}

/** Resolve the display type string for the type column. */
function resolveTypeName(node: SchemaNode): string {
  if (isSecretNode(node)) return "secret";
  if (isGroupNode(node)) return "object";
  const inner = unwrapAnyOf(node);
  if (inner.format === "path") return "path";
  return inner.type ?? "any";
}

/** True when the field's value looks like a filesystem path. */
function isPathLike(node: SchemaNode, key: string): boolean {
  const inner = unwrapAnyOf(node);
  if (inner.format === "path") return true;
  // Heuristic fallback: key ends with _dir, _file, _path
  return /_(?:dir|file|path)$/.test(key);
}

/** Get the ui hints from a node. Returns an empty object if none or if the node is undefined. */
function uiHints(node: SchemaNode | undefined | null): UiHints {
  if (!node) return {};
  return (node.ui as UiHints | undefined) ?? {};
}

/** Sort keys by ui.order, preserving declaration order as the tiebreaker. */
function sortedByOrder(keys: string[], props: Record<string, SchemaNode>): string[] {
  return [...keys].sort((a, b) => {
    const oa = uiHints(props[a]).order ?? Infinity;
    const ob = uiHints(props[b]).order ?? Infinity;
    if (oa !== ob) return oa - ob;
    return keys.indexOf(a) - keys.indexOf(b);
  });
}

function SecretValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span class={styles.valSecretUnset}>not set</span>;
  }
  return (
    <span class={styles.valSecret} aria-label="masked secret">
      <span class={styles.lockIcon} aria-hidden="true">
        🔒
      </span>
      {String(value)}
    </span>
  );
}

function BoolValue({ value }: { value: boolean }) {
  return (
    <Badge variant={value ? "success" : "neutral"} size="sm">
      {value ? "yes" : "no"}
    </Badge>
  );
}

function ListValue({ value }: { value: unknown[] }) {
  if (value.length === 0) {
    return <span class={styles.valListEmpty}>empty list</span>;
  }
  return (
    <span class={styles.valList}>
      {value.map((item, i) => (
        <span key={i} class={styles.valListItem}>
          {String(item)}
        </span>
      ))}
    </span>
  );
}

export function ExpandableValue({ value }: { value: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const label = Array.isArray(value)
    ? `[${(value as unknown[]).length} items]`
    : `{${Object.keys(value as Record<string, unknown>).length} keys}`;

  return (
    <span>
      <button type="button" class={styles.expandBtn} onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
          <polyline
            points={expanded ? "2,4 6,8 10,4" : "4,2 8,6 4,10"}
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
          />
        </svg>
        {label}
      </button>
      {expanded && <pre class={styles.expandedPre}>{JSON.stringify(value, null, 2)}</pre>}
    </span>
  );
}

function FieldValue({ node, value, fieldKey }: { node: SchemaNode; value: unknown; fieldKey: string }) {
  const hints = uiHints(node);

  // Secret fields — style them distinctly regardless of value.
  if (isSecretNode(node)) {
    return <SecretValue value={value} />;
  }

  if (value === null || value === undefined) {
    return <span class={styles.valNull}>—</span>;
  }

  // widget override from ui hints.
  if (hints.widget === "path" || isPathLike(node, fieldKey)) {
    return <code class={styles.valPath}>{String(value)}</code>;
  }

  if (typeof value === "boolean") {
    return <BoolValue value={value} />;
  }

  if (typeof value === "number") {
    return <span class={styles.valNumber}>{value}</span>;
  }

  if (Array.isArray(value)) {
    // Short arrays (all strings/numbers) render as chips; large or complex ones expand.
    const allPrimitive = value.every((v) => typeof v === "string" || typeof v === "number");
    if (allPrimitive) return <ListValue value={value} />;
    return <ExpandableValue value={value} />;
  }

  if (typeof value === "object") {
    return <ExpandableValue value={value} />;
  }

  return <span class={styles.valString}>{String(value)}</span>;
}

interface SectionProps {
  title: string;
  fields: Array<{ key: string; node: SchemaNode; value: unknown }>;
}

function ConfigSection({ title, fields }: SectionProps) {
  if (fields.length === 0) return null;

  return (
    <section
      class={styles.group}
      data-testid={`config-section-${title
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^a-z0-9-]/g, "")}`}
    >
      <h2 class="ht-section-label">{title}</h2>
      <Card variant="config">
        <table class={clsx("ht-table ht-table--compact", styles.configTable)}>
          <tbody>
            {fields.map(({ key, node, value }) => {
              const hints = uiHints(node);
              const label = hints.label ?? humanizeKey(key);
              const help = node.description;
              const typeName = resolveTypeName(node);

              return (
                <tr key={key} data-testid={`config-field-${key}`}>
                  <td class={styles.colLabel}>
                    <div class={styles.fieldLabel}>{label}</div>
                    {help && <div class={styles.fieldHelp}>{help}</div>}
                  </td>
                  <td class={styles.colValue} data-testid={`config-value-${key}`}>
                    <FieldValue node={node} value={value} fieldKey={key} />
                  </td>
                  <td class={styles.colType}>{typeName}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </section>
  );
}

/**
 * Render a JSON schema + values pair as grouped, labeled, type-formatted config sections.
 *
 * Both the global Config page and the per-app Config tab use this component.
 * The caller is responsible for passing the right values field from the endpoint
 * response (config_values for /api/config, app_config for /api/apps/{key}/config).
 */
export function ConfigSchemaView({ schema, values, emptyMessage }: ConfigSchemaViewProps) {
  const properties = (schema.properties ?? {}) as Record<string, SchemaNode>;
  const allKeys = Object.keys(properties);

  if (allKeys.length === 0) {
    return (
      <EmptyState
        title={emptyMessage ?? "no configuration fields"}
        body="this config has no fields defined in its schema."
      />
    );
  }

  // Split into scalar fields and group fields.
  const scalarKeys: string[] = [];
  const groupKeys: string[] = [];

  for (const key of allKeys) {
    const node = properties[key];
    if (isGroupNode(node)) {
      groupKeys.push(key);
    } else {
      scalarKeys.push(key);
    }
  }

  const orderedScalars = sortedByOrder(scalarKeys, properties);
  const orderedGroups = sortedByOrder(groupKeys, properties);

  // Build the scalar "general" section.
  const scalarFields = orderedScalars.map((key) => ({
    key,
    node: properties[key],
    value: values[key] ?? null,
  }));

  // Build one section per group.
  const groupSections = orderedGroups.map((key) => {
    const groupNode = properties[key];
    const hints = uiHints(groupNode);
    const title = hints.group_label ?? humanizeKey(key);

    // Get the group's own properties, unwrapping anyOf if needed.
    const innerNode = unwrapAnyOf(groupNode);
    const groupProps = (innerNode.properties ?? {}) as Record<string, SchemaNode>;
    const groupValues = (values[key] ?? {}) as ConfigRecord;

    const orderedFieldKeys = sortedByOrder(Object.keys(groupProps), groupProps);
    const fields = orderedFieldKeys.map((fk) => ({
      key: fk,
      node: groupProps[fk],
      value: groupValues[fk] ?? null,
    }));

    return { key, title, fields };
  });

  return (
    <div class={styles.groups} data-testid="config-schema-view">
      {scalarFields.length > 0 && <ConfigSection title="general" fields={scalarFields} />}
      {groupSections.map(({ key, title, fields }) => (
        <ConfigSection key={key} title={title} fields={fields} />
      ))}
    </div>
  );
}
