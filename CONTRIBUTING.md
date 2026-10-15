# Contributing to Hassette

Thank you for your interest in contributing to Hassette! We welcome contributions of all kinds.

## Ways to Contribute

- 🐛 **Report bugs** - Open an issue describing the problem
- 💡 **Suggest features** - Open an issue with your idea
- 📝 **Improve documentation** - Fix typos, clarify explanations, add examples
- 🔧 **Submit code** - Fix bugs or implement features

## Getting Started

### Development Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/NodeJSmith/hassette.git
   cd hassette
   ```

2. **Install dependencies**

   We use [uv](https://docs.astral.sh/uv/) for package management:

   ```bash
   uv sync
   ```

3. **Install prek hooks**

   We use [prek](https://prek.j178.dev/) (a fast, Rust-based pre-commit runner).
   [mise](https://mise.jdx.dev/) manages the version (pinned in `mise.toml`):

   ```bash
   mise install
   prek install
   ```

### Running Tests

Run the full test suite:

```bash
uv run nox -s tests
```

Run tests with coverage:

```bash
uv run nox -s tests_with_coverage
```

### Code Quality

We use several tools to maintain code quality:

- **Ruff** - Linting and formatting
- **Pyright** - Type checking
- **prek** - Automated checks before commits

Run checks manually:

```bash
# Format code
uv run ruff format .

# Run linter
uv run ruff check --fix .

# Type checking
uv run pyright
```

## Pull Request Process

1. **Create a branch** for your changes
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

2. **Make your changes** following our code style

3. **Add tests** for new functionality

4. **Run the test suite** to ensure everything passes

5. **Update documentation** if needed

6. **Commit your changes** with clear, descriptive messages

7. **Push and create a PR** targeting the `main` branch

### PR Guidelines

- Keep PRs focused on a single issue/feature
- Include tests for new functionality
- Update documentation as needed
- Follow existing code style and conventions
- Ensure all tests pass and prek checks succeed

## AI-Assisted Contributions

Hassette is built with AI coding agents (see [How Hassette Is Built](https://hassette.readthedocs.io/en/stable/pages/how-hassette-is-built/)), so AI-assisted pull requests are welcome. A few things I ask:

- Read and run what you submit. You're responsible for every line, so if you can't explain why something is there, take it out or ask about it in the PR.
- Mention in the PR description which AI tool you used and what it did (wrote the code, the tests, the docs). Autocomplete doesn't need a mention.
- For anything beyond a small fix, open an issue and agree on the approach before generating code.

I may close a PR that looks like unreviewed agent output.

## Code Style

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use type hints everywhere
- Write docstrings for all public APIs (Google style)
- Keep functions focused and concise

### Docstrings

Use Google-style docstrings with fenced code blocks for examples:

```python
def my_function(param: str) -> int:
    """Brief description of function.

    Longer description if needed.

    Args:
        param: Description of parameter.

    Returns:
        Description of return value.

    Examples:

    ```python
    result = my_function("example")
    print(result)
    ```
    """
    pass
```

### Type Hints

- Use type hints for all function signatures
- Leverage Pydantic models for data validation
- Use `typing` and `typing_extensions` features appropriately

### Wire Contract

The HTTP/WebSocket wire contract — every served model, enum, and Literal — lives in
`wire/src/hassette_wire/`, not in `src/hassette`. A field added to a wire model after the first
published `hassette-wire` release must be optional with a default, so a client built against a
newer release can still parse a response from a server still running an older release that
hasn't added the field yet. Adding an enum member or a new Literal value is a version-skew
change in the opposite direction (older client, newer server), which the client package's
lenient parsing handles.

A PR that deliberately breaks the wire contract adds one line per reported change to
`tools/wire_compat_ignore.txt`, copied from the compatibility check's output. Clear those lines
out once the release that ships the break goes out — the file should stay empty otherwise.

The automated compatibility check (`tools/check_wire_compat.py`) covers the HTTP contract
(`openapi.json`) only. WS payloads follow the same rules but have no automated cross-release
check yet — a WS-breaking change relies on review, not CI.

## Documentation

Documentation is built with [MkDocs](https://www.mkdocs.org/) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/).

### Building Documentation Locally

```bash
uv run mkdocs serve
```

Then visit http://localhost:8000

### Documentation Guidelines

- Use clear, simple language
- Include practical examples
- Follow progressive disclosure (simple → complex)
- Test all code examples

### Example and Demo Apps

`examples/` holds only apps users can copy as templates for their own automations. The apps that put
the web UI into specific states for the demo stack and docs screenshots (a deliberately failing job, a
crashed instance, a blocked event loop) are framework dev tooling and live in `scripts/demo_apps/`.
`scripts/demo_apps/hassette.toml` loads both sets for `mise run demo` and
`scripts/capture_screenshots.py`. A new screenshot fixture goes in `scripts/demo_apps/`, not
`examples/`.

## Questions?

- Open an issue for questions about contributing
- Check existing issues and PRs for similar topics
- Join discussions in issues and PRs

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
