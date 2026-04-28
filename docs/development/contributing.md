# Contributing

Thank you for your interest in contributing to MacroTrace!

## Development Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd macrotrace
```

2. Install dependencies with uv:
```bash
uv sync --all-groups
```

3. Activate the virtual environment:
```bash
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

## Code Style

MacroTrace uses [Black](https://black.readthedocs.io/) for code formatting
and [Ruff](https://docs.astral.sh/ruff/) for linting:

```bash
# Format all code
uv run black macrotrace/ tests/

# Check formatting without changes
uv run black --check macrotrace/ tests/

# Lint and auto-fix
uv run ruff check --fix macrotrace/ tests/
```

### Pre-commit Hooks

The repository ships a [pre-commit](https://pre-commit.com/) config that
runs Black and Ruff (plus a few standard hygiene checks) on every commit.
After cloning and running `uv sync --all-groups`, register the git hook
once:

```bash
uv run pre-commit install
```

From this point on, every `git commit` will run the hooks against your
staged files. To run them manually against the whole repo (useful right
after install or before opening a PR):

```bash
uv run pre-commit run --all-files
```

To bump pinned tool versions in `.pre-commit-config.yaml`:

```bash
uv run pre-commit autoupdate
```

## Documentation

Documentation is built using MkDocs with Material theme and mkdocstrings for API documentation.

### Writing Docstrings

Use Google-style docstrings:

```python
def my_function(param1: str, param2: int) -> bool:
    """Short description of function.

    Longer description if needed.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When something is wrong

    Examples:
        >>> my_function("test", 42)
        True
    """
    pass
```

### Building Documentation

```bash
# Serve locally with live reload
sh scripts/serve_docs.sh
# or
mkdocs serve

# Build static site
sh scripts/build_docs.sh
# or
mkdocs build
```

The API reference is automatically generated from docstrings using mkdocstrings.

### Adding Documentation Pages

1. Create a new `.md` file in `docs/`
2. Add it to the `nav` section in `mkdocs.yml`
3. Use mkdocstrings syntax to include auto-generated API docs:

```markdown
# My New Page

::: macrotrace.my_module.MyClass
```

## Adding a New Data Source

To add support for a new data provider:

1. Create a new file in `macrotrace/sources/` (e.g., `newsource.py`)
2. Extend the base classes:

```python
from macrotrace.sources.base import (
    BaseAPIClient,
    BaseDatasetManager,
    BaseSeriesManager,
    BaseObservationManager
)

class NewSourceAPIClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            base_url='https://api.newsource.com',
            cache_name='newsource_cache'
        )

class NewSourceDatasetManager(BaseDatasetManager):
    def __init__(self):
        super().__init__(
            source='NEWSOURCE',
            api_client=NewSourceAPIClient()
        )

# Implement required methods...
```

3. Add tests in `tests/sources/newsource/`
4. Update documentation

## Project Structure

```
macrotrace/
├── macrotrace/           # Main package
│   ├── models/          # Database models
│   │   ├── db.py       # Database setup
│   │   └── mt/         # MacroTrace models
│   ├── sources/        # Data source connectors
│   │   ├── base.py     # Base classes
│   │   ├── fred.py     # FRED implementation
│   │   └── ons.py      # ONS implementation
│   └── graphing.py     # Visualization utilities
├── tests/              # Test suite
├── docs/               # Documentation
├── notebooks/          # Example notebooks
└── scripts/           # Utility scripts
```

## Questions?

Open an issue on GitHub or contact the maintainer.
