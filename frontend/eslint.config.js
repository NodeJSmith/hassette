import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import simpleImportSort from "eslint-plugin-simple-import-sort";
// Fork of eslint-plugin-react-hooks that adds `additionalStableHooks` — lets us
// teach exhaustive-deps that useSignal/useComputed return stable refs, avoiding
// ~14 false-positive suppressions. Wraps the upstream plugin for all other rules.
// Single-maintainer fork (Donov4n); if it falls behind upstream, fall back to
// the original plugin + per-line eslint-disable comments.
import reactHooks from "eslint-plugin-react-hooks-configurable";
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
      "react-hooks-configurable": reactHooks,
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
      "eqeqeq": ["error", "always"],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",
      "react-hooks-configurable/rules-of-hooks": "error",
      "react-hooks-configurable/exhaustive-deps": [
        "warn",
        {
          additionalStableHooks: {
            useSignal: true,
            useComputed: true,
          },
        },
      ],
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
