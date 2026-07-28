import { ColorTokens } from "../components/design/color-tokens";
import { ComponentShowcase } from "../components/design/component-showcase";
import { SpacingTokens } from "../components/design/spacing-tokens";
import { TypographyTokens } from "../components/design/typography-tokens";
import { useDocumentTitle } from "../hooks/use-document-title";

export function DesignPage() {
  useDocumentTitle("Design System");

  return (
    <div className="flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2">
      <header className="flex items-baseline gap-4 border-b border-border pb-3">
        <h1>Design System</h1>
      </header>
      <div className="flex max-w-[960px] flex-col gap-10 p-6">
        <ColorTokens />
        <TypographyTokens />
        <SpacingTokens />
        <ComponentShowcase />
      </div>
    </div>
  );
}
