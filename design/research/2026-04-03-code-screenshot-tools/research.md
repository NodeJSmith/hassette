---
proposal: "Replace manual VS Code screenshots in documentation with programmatically generated code images"
date: 2026-04-03
status: Draft
flexibility: Exploring
motivation: "Manual screenshots are fragile, hard to maintain, and break when themes/code change. Programmatic generation enables CI automation and consistency."
constraints: "Must integrate with MkDocs Material build pipeline; must run headlessly in CI; Python ecosystem preferred but not required"
non-goals: "Reproducing actual VS Code autocomplete popups (acknowledged as out of scope for static generation)"
depth: normal
---

# Research Brief: Programmatic Code Screenshot Generation

**Initiated by**: Investigation of tools that can generate VS Code-style code images from source files, replacing manual screenshots in hassette documentation.

## Context

### What prompted this

The hassette documentation (MkDocs Material, hosted on ReadTheDocs) needs screenshots showing VS Code with syntax-highlighted code, type annotations, and (ideally) autocomplete popups. Taking real screenshots is manual, fragile, and impossible to automate in CI. The goal is to find tools that can generate these images from code/config at build time.

### Current state

The docs currently use:
- **12 PNG screenshots** in `docs/_static/` -- mostly web UI screenshots and Home Assistant token setup screenshots
- **MkDocs Material** with `pymdownx.highlight` for in-page syntax highlighting (Pygments-based)
- **pymdownx.snippets** for including code from external files
- No existing code-to-image pipeline

The `mkdocs.yml` already has `pymdownx.superfences` with custom fence support (currently only mermaid), which is the natural extension point for a build-time image generation plugin.

### Key constraints

- Must run headlessly in CI (GitHub Actions on Linux)
- Should produce consistent output across environments (no font rendering differences)
- VS Code theme fidelity is desirable but not strictly required -- "looks like code in a nice editor" is sufficient
- Python-native solutions are preferred for MkDocs integration but CLI tools callable from a build script are acceptable
- SVG output is preferred for docs (scales cleanly, smaller files) but PNG is acceptable

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Build pipeline | `mkdocs.yml`, possibly new MkDocs plugin or pre-build script | Low | Low -- additive change |
| CI workflow | `.github/workflows/` docs build step | Low | Low -- just adding a tool install step |
| Source code snippets | New directory for screenshot source files (e.g., `docs/_code/`) | Low | None |
| Existing docs | Update `![...]()` references to point to generated images | Low | None |

### What already supports this

- `pymdownx.superfences` custom fences could wrap a code-to-image tool
- `pymdownx.snippets` already supports including code from files -- the same source files could feed both inline code blocks and image generation
- MkDocs `gen-files` plugin is already installed and could run a pre-build script
- The `tools/gen_ref_pages.py` pattern shows the project already uses build-time code generation

### What works against this

- No existing Node.js toolchain in the project (rules out some JS-only tools unless added as a dev dependency)
- ReadTheDocs build environment may have limited tool availability (pre-installed tools only, or pip-installable)
- Font rendering differences between local dev and CI can produce slightly different PNG output (SVG avoids this)

## Options Evaluated

### Option A: Freeze (Charmbracelet) -- Recommended for simplicity

**How it works**: Freeze is a Go CLI that reads source files or stdin and generates PNG, SVG, or WebP images with syntax highlighting, window chrome, line numbers, and customizable themes. It uses Chroma (Go port of Pygments) for highlighting. A pre-build script reads code snippets from a directory and generates images before MkDocs runs.

**Pros**:
- Single static binary -- trivial to install in CI (`go install` or download release binary)
- SVG output -- scales perfectly, no font rendering issues
- Window chrome (macOS-style title bar) built in -- looks like an editor screenshot
- Line numbers, padding, shadows, rounded corners all configurable
- Interactive TUI for initial configuration, saves to JSON for reproducibility
- Can execute commands and capture ANSI output (useful for terminal screenshots too)
- Active maintenance (Charmbracelet is a well-funded team)

**Cons**:
- Chroma themes are NOT VS Code themes -- they are Pygments-compatible styles. Dracula, Monokai, etc. are available but you cannot load a `.tmTheme` or VS Code JSON theme directly
- No TypeScript/Python type annotation rendering beyond what syntax highlighting provides (no "hover" or "autocomplete" simulation)
- Go dependency in the build pipeline (though it is just a single binary)
- Cannot fake IDE chrome beyond the basic window titlebar

**Effort estimate**: Small -- install binary, write a short shell script to process code files, add to CI

**Dependencies**: `freeze` binary (Go, ~15MB static binary)

**Example workflow**:
```bash
# In CI or pre-build script:
freeze docs/_code/app_example.py \
  --output docs/_static/generated/app_example.svg \
  --theme dracula \
  --window \
  --show-line-numbers \
  --font.family "JetBrains Mono" \
  --padding 20
```

### Option B: Silicon (Rust CLI) -- Best VS Code theme fidelity

**How it works**: Silicon is a Rust CLI that uses syntect (the same TextMate grammar engine as VS Code) to tokenize and highlight code, then renders to PNG. It supports `.tmTheme` theme files, which means you can export your actual VS Code theme and use it directly.

**Pros**:
- **Exact VS Code theme fidelity** -- uses TextMate grammars and `.tmTheme` themes, the same engine VS Code uses internally
- Can load custom `.tmTheme` files (export from VS Code or download from the theme marketplace)
- Fast rendering (Rust, no browser)
- Line highlighting support (highlight specific lines)
- Window controls (macOS-style)
- Installable via `cargo install silicon` or Homebrew

**Cons**:
- **PNG only** -- no SVG output. This means font rendering differences across environments and larger file sizes
- Requires a Rust toolchain or pre-built binary in CI
- Fewer built-in themes than Freeze (must supply `.tmTheme` files for custom themes)
- Less actively maintained than Freeze (single maintainer)
- No window title text support
- Font availability in CI can be problematic for PNG rendering

**Effort estimate**: Small -- similar to Freeze but needs `.tmTheme` file management

**Dependencies**: `silicon` binary (Rust), `.tmTheme` file for desired theme, fonts installed in CI

### Option C: Shiki + shiki-image (Node.js) -- Best for programmatic control

**How it works**: Shiki is the syntax highlighter used by VS Code itself, running in Node.js. The `shiki-image` package wraps Shiki with image rendering (PNG, WebP, AVIF). A small Node.js script processes code files and generates images. Shiki natively supports all VS Code themes.

**Pros**:
- **Identical VS Code highlighting** -- Shiki IS VS Code's highlighter
- All VS Code themes available out of the box (`github-dark`, `one-dark-pro`, `dracula`, etc.)
- `@shikijs/twoslash` integration can render TypeScript type annotations, hover tooltips, and error squiggles -- the closest thing to "fake autocomplete" available
- Programmatic API allows fine-grained control
- Can generate HTML for web embedding as well as images
- Active ecosystem with many integrations

**Cons**:
- Adds Node.js as a build dependency (the project currently has no JS toolchain)
- `shiki-image` is experimental ("Contributors needed!" note in repo), only 149 stars
- Requires a Node.js script to orchestrate (more complex than a CLI one-liner)
- Image rendering quality depends on the `takumi` library (less battle-tested than native renderers)
- ReadTheDocs may not have Node.js available in the build environment (would need a pre-build step or custom build image)

**Effort estimate**: Medium -- requires adding Node.js toolchain, writing a generation script, managing the dependency

**Dependencies**: Node.js runtime, `shiki`, `shiki-image`, optional `@shikijs/twoslash`

### Option D: Pygments ImageFormatter (Python-native) -- Zero new dependencies

**How it works**: Pygments (already installed as a hassette dev dependency via `pymdownx.highlight`) has a built-in `ImageFormatter` that renders code to PNG using Pillow. A Python script in `tools/` generates images from code files.

**Pros**:
- **Zero new dependencies** -- Pygments is already in the dependency tree, Pillow is a standard Python package
- Python-native -- fits the existing toolchain perfectly
- Runs on ReadTheDocs without any special configuration
- Could be integrated as a MkDocs plugin or hooked into `gen-files`
- Many built-in styles (monokai, dracula, github-dark, etc.)

**Cons**:
- **Output looks like Pygments, not VS Code** -- the highlighting is close but not identical (Pygments uses its own grammar, not TextMate)
- PNG only (no SVG)
- No window chrome, title bar, or editor frame -- just raw highlighted code on a background
- Font rendering depends on system fonts and Pillow's text rendering (can look rough)
- No line numbers in the default image output (would need custom code)
- Would need a wrapper to add VS Code-like chrome (background, padding, rounded corners)

**Effort estimate**: Small-Medium -- Pygments part is trivial, but adding window chrome requires custom Pillow drawing code

**Dependencies**: `Pillow` (add to dev dependencies)

### Option E: Carbon / ray.so (browser-based) -- Not recommended

**How it works**: Carbon and ray.so are web apps that generate beautiful code images. CLI wrappers (`carbon-now-cli`, `rayso-api`) drive a headless browser to capture the output.

**Pros**:
- Beautiful output with many themes
- Well-known tools with good UI for one-off generation

**Cons**:
- **Requires a headless browser** (Chromium/Playwright) in CI -- heavy, slow, fragile
- Network dependency (carbon.now.sh must be reachable, or you self-host)
- Inconsistent rendering across browser versions
- Slow (seconds per image vs. milliseconds for native tools)
- `carbon-now-cli` uses Playwright under the hood

**Effort estimate**: Medium -- browser automation is inherently fragile

**Dependencies**: Node.js, Playwright, Chromium, network access

## Tool Comparison Matrix

| Feature | Freeze | Silicon | Shiki+image | Pygments | Carbon/ray.so |
|---------|--------|---------|-------------|----------|---------------|
| VS Code theme fidelity | Partial (Chroma) | Exact (.tmTheme) | Exact (native) | Partial (Pygments) | Partial |
| SVG output | Yes | No | No | No | No |
| PNG output | Yes | Yes | Yes | Yes | Yes |
| Window chrome | Yes | Yes | No (needs wrapper) | No | Yes |
| Line numbers | Yes | Yes | Via HTML only | Custom code needed | Yes |
| Headless CI | Yes (static binary) | Yes (static binary) | Yes (Node.js) | Yes (Python) | Fragile (browser) |
| No new runtime | No (Go) | No (Rust) | No (Node.js) | Yes (Python) | No (Node.js+browser) |
| Install complexity | Low (single binary) | Low (single binary) | Medium | None | High |
| MkDocs integration | Pre-build script | Pre-build script | Pre-build script | Plugin or gen-files | Pre-build script |
| Maintenance | Active (Charm team) | Moderate (1 person) | Experimental | Stable (Pygments core) | Stable but 3rd-party CLIs |
| Type annotation rendering | No | No | Yes (twoslash) | No | No |

## Concerns

### Technical risks
- **PNG font rendering variance**: Silicon, Pygments, and shiki-image all produce PNGs that depend on system fonts. CI environments may render differently than local dev. SVG (Freeze) avoids this entirely.
- **ReadTheDocs build environment**: RTD uses a containerized build. Installing Go/Rust binaries requires a custom build step in `.readthedocs.yaml`. Node.js requires explicit configuration. Only Python tools run natively.
- **shiki-image stability**: The library is self-described as experimental. It could break or be abandoned.

### Complexity risks
- Adding a Node.js toolchain to a Python-only project increases maintenance surface significantly.
- Any image generation pipeline adds a "rebuild images" step that developers must remember (or automate).
- Caching generated images in git vs. generating at build time is a design decision with trade-offs either way.

### Maintenance risks
- Generated images committed to git grow the repo over time (binary files in git history).
- Generated images at build time add CI build time and require the tool to remain available.
- Theme updates require regenerating all images.

## Open Questions

- [ ] Are the VS Code screenshots meant to show the hassette API (autocomplete, type hints) or just general code examples? If the former, twoslash-style type annotations (Shiki Option C) become much more valuable.
- [ ] Does ReadTheDocs allow custom build steps that install non-Python binaries? If not, Options A and B would need images pre-generated and committed to git.
- [ ] Should generated images be committed to git (reproducible, no build-time generation) or generated at build time (always fresh, but adds CI complexity)?
- [ ] What VS Code theme should the screenshots use? This affects which tools are viable (only Silicon and Shiki can match an arbitrary VS Code theme exactly).
- [ ] Is the "window chrome" (title bar, traffic lights) important for the visual style, or is clean highlighted code sufficient?

## Recommendation

**Start with Freeze (Option A)** for its combination of simplicity, SVG output, and minimal CI overhead. It produces clean, professional code images with editor-like window chrome, requires no runtime beyond a single binary, and SVG output eliminates font rendering issues entirely.

**Upgrade to Silicon (Option B) later** if exact VS Code theme matching becomes a priority -- it is nearly as simple but limited to PNG.

**Consider Shiki (Option C) only if** the documentation needs to show type annotations, hover tooltips, or autocomplete-style information rendered inline in code images. The `@shikijs/twoslash` integration is the only tool that can simulate IDE intelligence features, but it comes at the cost of adding Node.js to the build chain.

**Skip Carbon/ray.so (Option E)** entirely -- browser automation is the wrong tool for a build pipeline.

### Suggested implementation approach

1. Create a `docs/_code/` directory with standalone Python files for each code image
2. Write a shell script (`tools/gen_code_images.sh`) that runs `freeze` on each file
3. Output SVGs to `docs/_static/generated/`
4. Add the script to the `gen-files` pre-build hook or as a Makefile target
5. Commit generated SVGs to git (small files, deterministic output)
6. Add `freeze` installation to the CI docs workflow

### Suggested next steps

1. Install Freeze locally and test with a representative hassette code snippet to evaluate visual quality
2. If the result is good enough, write the generation script and integrate with `mkdocs serve`
3. If VS Code theme fidelity matters, test Silicon with the user's actual `.tmTheme` as a comparison
4. If type annotations/hover info is needed in screenshots, prototype with Shiki + twoslash before committing to a direction

## Sources

- [Silicon (Rust CLI)](https://github.com/Aloxaf/silicon)
- [Freeze (Charmbracelet)](https://github.com/charmbracelet/freeze)
- [Shiki syntax highlighter](https://shiki.style/)
- [shiki-image](https://github.com/pi0/shiki-image)
- [@shikijs/twoslash](https://shiki.style/packages/twoslash)
- [Carbon](https://carbon.now.sh/)
- [carbon-now-cli](https://github.com/mixn/carbon-now-cli)
- [ray.so](https://www.ray.so/)
- [Rayso-API](https://github.com/akashrchandran/Rayso-API)
- [Pygments ImageFormatter](https://pygments.org/docs/formatters/)
- [code2image (Pygments + Pillow)](https://github.com/axju/code2image)
- [CodeSnap VS Code extension](https://marketplace.visualstudio.com/items?itemName=adpyke.codesnap)
- [remark-code-screenshot](https://github.com/Swizec/remark-code-screenshot)
- [MkDocs Material code blocks](https://squidfunk.github.io/mkdocs-material/reference/code-blocks/)
