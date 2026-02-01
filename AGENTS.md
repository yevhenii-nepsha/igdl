# AGENTS.md — Coding Agent Instructions for igdl

## Project Overview

**igdl** is a Python CLI tool for downloading Instagram media (photos/videos).
Python 3.10+, synchronous, uses `requests` + `rich` + optional `aria2c`.
Flat single-package structure under `igdl/` — no sub-packages.

## Build / Install / Run

```bash
# Install in dev mode (editable) with dev dependencies
pip install -e ".[dev]"

# Run the CLI
igdl <username> -n 5
python -m igdl <username> -n 5
```

## Linting and Type Checking

```bash
# Lint (ruff — checks pycodestyle, pyflakes, isort, pep8-naming, pyupgrade)
ruff check igdl/

# Auto-fix lint issues
ruff check igdl/ --fix

# Format code
ruff format igdl/

# Check formatting without changing files
ruff format igdl/ --check

# Type checking (mypy strict mode)
mypy igdl/

# Quick syntax check (no dependencies needed)
python -m py_compile igdl/*.py
```

## Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_models.py

# Run a single test function
pytest tests/test_models.py::test_profile_from_api

# Run tests matching a keyword
pytest -k "rate_limiter"

# Verbose output
pytest -v
```

Note: When adding features, add corresponding tests under `tests/` using pytest.

## Code Style

### General Rules

- **Line length**: 100 characters
- **Python version**: 3.10+ features allowed and expected
- **Type hints**: Required on ALL functions (params + return), enforced by `mypy --strict`
- **Docstrings**: Google style on every module, class, and public method
- **Formatter/linter**: ruff (configured in `pyproject.toml`)

### Imports

Three groups separated by blank lines, each sorted alphabetically:

```python
# 1. Standard library
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# 2. Third-party
import requests
from rich.console import Console

# 3. Local (always relative imports)
from .exceptions import ApiError, RateLimitError
from .models import Post, Profile
```

- Always use **relative imports** for local modules (`.module`, never `igdl.module`)
- Multi-name imports use parenthesized multi-line format with trailing commas
- Enforced by ruff rule `"I"` (isort)

### Type Annotations

- Use modern union syntax: `str | None` (not `Optional[str]`)
- Use lowercase generics: `list[Post]`, `dict[str, Any]`, `set[str]` (not `List`, `Dict`)
- Use `collections.abc` for abstract types: `Iterator`, `Sequence` (not from `typing`)
- Use `typing.Any` for untyped external data (API JSON)
- Always annotate `-> None` on `__init__` and void methods
- Use string-quoted forward references for self-referencing returns: `-> "Profile"`

### Naming Conventions

| Element             | Convention         | Example                          |
|---------------------|--------------------|----------------------------------|
| Files/modules       | `snake_case`       | `rate_limiter.py`                |
| Classes             | `PascalCase`       | `InstagramClient`, `RateLimiter` |
| Functions/methods   | `snake_case`       | `get_profile()`, `wait_if_needed()` |
| Private methods     | `_snake_case`      | `_create_session()`, `_request()` |
| Variables           | `snake_case`       | `retry_after`, `downloaded_count` |
| Module constants    | `UPPER_SNAKE_CASE` | `POSTS_DOC_ID`, `USER_AGENT`     |
| Class constants     | `UPPER_SNAKE_CASE` | `WINDOW_SECONDS`, `MAX_REQUESTS` |

### Error Handling

Custom exception hierarchy rooted at `IgdlError` in `exceptions.py`:

```
IgdlError (base)
├── ProfileNotFoundError(username)
├── PrivateProfileError(username)
├── RateLimitError(retry_after)
├── AuthenticationError
├── DownloadError(url, reason)
└── ApiError(status_code, message)
```

- Raise domain-specific exceptions with structured attributes (not just message strings)
- Use exception chaining: `raise ApiError(...) from e`
- Retry loops use exponential backoff: `wait_time = 2 ** attempt`
- `main()` in `cli.py` catches `IgdlError` at the top level; inner code catches specific subtypes
- Handle `KeyboardInterrupt` at CLI boundary (exit code 130)

### Data Models

- Use `@dataclass` for all data models (no Pydantic/attrs)
- Required fields first, optional/default fields after
- Use `field(default_factory=list)` for mutable defaults
- Use `@classmethod` factory methods for constructing from external data
- Use `@property` for computed/derived values

### Output and Logging

No `logging` module. Use `rich.console.Console` singleton (module-level `console`):

- `[dim]...[/dim]` — debug/verbose info
- `[yellow]...[/yellow]` — warnings
- `[red]...[/red]` — errors
- `[green]...[/green]` — success messages
- `[cyan]...[/cyan]` — status/progress

Respect the `quiet` flag: wrap output in `if not self.quiet:`.

## Architecture

Layered: `cli.py` -> `downloader.py` -> `client.py` -> `models.py` / `exceptions.py`

- One responsibility per module
- `__init__.py` re-exports public API with categorized `__all__`
- `InstagramClient` supports context manager protocol (`with` statement)
- `DownloadArchive` supports dunder protocols (`__len__`, `__contains__`, `__bool__`)

## Where to Add New Code

| What               | Where              |
|---------------------|--------------------|
| New API endpoint    | `client.py`        |
| New data model      | `models.py`        |
| New download type   | `downloader.py`    |
| New CLI option      | `cli.py`           |
| New exception       | `exceptions.py`    |
| New config option   | `config.py`        |

## Highlights Feature

Downloads all highlight reels from a profile. Requires cookies (`--cookies`).

```bash
igdl username --highlights --cookies cookies.txt
```

### API Endpoints (both require cookies)

```
GET /api/v1/highlights/{user_id}/highlights_tray/
    → List of highlights (id, title, media_count)

GET /api/v1/feed/reels_media/?reel_ids=highlight:{id}
    → Items (photos/videos) for a single highlight
```

### Directory Structure

```
{output}/{username}/highlights/{slug}/
    {username}_{media_id}.{ext}
```

- `slug` = filesystem-safe version of highlight title (preserves unicode/emoji)
- Duplicate titles get suffix: `travel/`, `travel_2/`
- Archive tracks `media_id` to skip already-downloaded items

### Key Files

| What | Where |
|------|-------|
| Models: `Highlight`, `HighlightItem`, `slugify()` | `models.py` |
| API: `get_highlights()`, `get_highlight_items()` | `client.py` |
| Download orchestration | `downloader.py` (`download_highlights()`) |
| Behavior delays | `behavior.py` (`highlight_tray_delay()`, `highlight_switch_delay()`) |

### Safety

- Cookies mode auto-disables proxy (`cli.py`) to avoid account flagging
- Human-like delays between highlights (2-5s per highlight switch)
- Rate limiter runs in conservative mode (75 req/11min, 0.5-5s delays)

## Important Notes

- CDN downloads must use clean requests (no Instagram headers)
- Instagram may ignore the `first` parameter in GraphQL; typically returns 12 posts/page
- Aria2c downloads in batches of 50 to avoid URL expiration
- All project config lives in `pyproject.toml` (no setup.py/cfg/requirements.txt)
- Build backend: `hatchling`
