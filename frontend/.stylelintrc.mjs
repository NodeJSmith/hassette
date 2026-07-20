export default {
  extends: "stylelint-config-standard",
  rules: {
    // CSS Modules: composes uses camelCase class names, :global() is valid,
    // and composes is a non-standard property
    "value-keyword-case": [
      "lower",
      {
        ignoreProperties: ["composes", "font-family", "/^--font/"],
        ignoreKeywords: ["currentColor", "optimizeLegibility"],
      },
    ],
    "selector-pseudo-class-no-unknown": [true, { ignorePseudoClasses: ["global"] }],
    "property-no-unknown": [true, { ignoreProperties: ["composes"] }],

    // Reset/normalize: vendor prefixes for Safari text-size-adjust and font-smoothing
    "property-no-vendor-prefix": [
      true,
      { ignoreProperties: ["-webkit-text-size-adjust", "-webkit-font-smoothing"] },
    ],

    // Naming: CSS Modules generates camelCase classes, custom properties use
    // project conventions, keyframes use camelCase
    "selector-class-pattern": null,
    "custom-property-pattern": null,
    "keyframes-name-pattern": null,

    // Structural: empty blocks used as CSS Module hooks for JS-applied classes,
    // longhand properties preferred for readability in layout code
    "block-no-empty": null,
    "declaration-block-no-redundant-longhand-properties": null,
    "no-descending-specificity": null,

    // Deprecated property: clip used alongside clip-path as a legacy fallback
    // in sr-only/tooltip patterns
    "property-no-deprecated": null,

    // Notation preferences: tokens.css uses established notation for oklch,
    // rgba, and import paths — enforcing modern notation would churn the
    // design token file for no functional benefit
    "import-notation": null,
    "media-feature-range-notation": null,
    "color-function-notation": null,
    "color-function-alias-notation": null,
    "alpha-value-notation": null,
    "lightness-notation": null,
    "hue-degree-notation": null,
    "color-hex-length": null,
    "font-family-name-quotes": null,
    "selector-not-notation": null,

    // Formatting: handled by prettier
    "rule-empty-line-before": null,
    "comment-empty-line-before": null,
    "declaration-empty-line-before": null,
  },
};
