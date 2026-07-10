import { ColorTokens } from "../components/design/color-tokens";
import { ComponentShowcase } from "../components/design/component-showcase";
import { SpacingTokens } from "../components/design/spacing-tokens";
import { TypographyTokens } from "../components/design/typography-tokens";
import { useDocumentTitle } from "../hooks/use-document-title";
import styles from "./design.module.css";

export function DesignPage() {
  useDocumentTitle("Design System");

  return (
    <div class="ht-page">
      <header class="ht-page-header">
        <h1>Design System</h1>
      </header>
      <div class={styles.content}>
        <ColorTokens />
        <TypographyTokens />
        <SpacingTokens />
        <ComponentShowcase />
      </div>
    </div>
  );
}
