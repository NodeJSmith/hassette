import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import reactHooks from "eslint-plugin-react-hooks";
import eslintConfigPrettier from "eslint-config-prettier";

export default tseslint.config(
  {
    ignores: ["dist", "node_modules", "../src/hassette/web/static/spa"],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "simple-import-sort": simpleImportSort,
      "react-hooks": reactHooks,
    },
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "eqeqeq": ["error", "always"],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              regex: "^\\.\\.\\/\\.\\.\\/\\.\\.\\/.+",
              message: "Use the @/ path alias instead of deep relative imports (3+ levels).",
            },
          ],
        },
      ],
      // Module-level Tailwind class-string constants use one naming convention (_CLASS/_CLASSES
      // suffix) so tooling — specifically oxlint-tailwindcss's `variablePatterns` config in
      // .oxlintrc.json — can find every one of them. A second convention here creates a lint
      // blind spot: a class string assigned to a name the pattern doesn't match can go silently
      // unvalidated. Use FOO_CLASS / FOO_CLASSES instead of fooClassName / fooClassNames.
      // Scoped to `init.type=Literal|TemplateLiteral` so it only fires on a literal string
      // assignment (the actual class-string case) and not on unrelated bindings that merely
      // share the suffix, e.g. `const merged = linkClassName;` rebinding a component prop.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "VariableDeclarator[init.type=/^(Literal|TemplateLiteral)$/] > Identifier.id[name=/ClassNames?$/]",
          message: "Name class-string constants with a _CLASS/_CLASSES suffix (e.g. FOO_CLASS), not *ClassName(s).",
        },
      ],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-floating-promises": "off",
    },
  },
  eslintConfigPrettier,
);
