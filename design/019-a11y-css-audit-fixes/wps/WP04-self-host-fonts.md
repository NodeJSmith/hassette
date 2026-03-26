# WP04: Self-host fonts

**Lane:** todo
**Depends on:** none (parallel with WP01-03)

## Objective

Replace CDN-loaded Google Fonts with self-hosted woff2 files for offline operation.

## Tasks

### 1. Download font files

Download Latin-subset woff2 files (use google-webfonts-helper or fontsource):

- **DM Sans**: 400 (regular), 500 (medium), 700 (bold) — 3 files
- **JetBrains Mono**: 400 (regular), 500 (medium) — 2 files
- **Space Grotesk**: 400 (regular), 500 (medium), 600 (semibold), 700 (bold) — 4 files

Total: 9 files, ~200-300KB

### 2. Place in repo

- Create `frontend/public/fonts/`
- Commit all woff2 files
- Naming convention: `dm-sans-400.woff2`, `jetbrains-mono-500.woff2`, `space-grotesk-600.woff2`, etc.
- Add `*.woff2 binary` to `.gitattributes` (create file if needed) — prevents `core.autocrlf` from corrupting binary font files

### 3. Add `@font-face` declarations

In `global.css`, before the `@import` of `tokens.css` (or at the top of the file if no import exists). Keeps `tokens.css` strictly declarative (custom properties only):

```css
/* Self-hosted fonts — Latin subset
   DM Sans: 400, 500, 700
   JetBrains Mono: 400, 500
   Space Grotesk: 400, 500, 600, 700 */

@font-face {
  font-family: 'DM Sans';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/dm-sans-400.woff2') format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}
/* ... repeat for each weight/family */
```

### 4. Remove CDN references

In `frontend/index.html`, remove:
```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=..." rel="stylesheet" />
```

## Files

- `frontend/public/fonts/*.woff2` (9 new files)
- `frontend/src/global.css` (`@font-face` declarations at top of file)
- `.gitattributes` (add `*.woff2 binary`)
- `frontend/index.html` (remove CDN links)

## Verification

- Open browser devtools Network tab — confirm all fonts load from `/fonts/` not `fonts.googleapis.com`
- No 404s on any font file
- Visual comparison: typography should look identical before/after
- Test with network disabled — fonts must still load
- Verify `font-display: swap` behavior (text visible immediately, font swaps in)
- Check DM Sans bold (700) renders correctly — no browser-synthesized fake bold
