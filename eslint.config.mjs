import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["src/hassette/web/static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "script",
      globals: {
        ...globals.browser,
        Alpine: "readonly",
        htmx: "readonly",
      },
    },
    rules: {
      "max-len": ["warn", { code: 120, ignoreUrls: true, ignoreStrings: true }],
    },
  },
];
