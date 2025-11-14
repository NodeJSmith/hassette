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

3. **Install pre-commit hooks**

   ```bash
   uv run pre-commit install
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
- **Pre-commit** - Automated checks before commits

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
- Ensure all tests pass and pre-commit checks succeed

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

## Project Structure

```
src/hassette/
├── api/           # API client for Home Assistant
├── app/           # Base app classes
├── bus/           # Event bus and predicates
├── config/        # Configuration models
├── core/          # Core runtime
├── events/        # Event models
├── models/        # State and entity models
├── scheduler/     # Task scheduling
├── services/      # Background services
└── utils/         # Utility functions
```

## Questions?

- Open an issue for questions about contributing
- Check existing issues and PRs for similar topics
- Join discussions in issues and PRs

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
