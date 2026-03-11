# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`stroke-memorize` is a Python application for memorizing stroke order and how to write characters (e.g., Chinese/Japanese kanji). It is in early development — `main.py` currently contains only a stub.

## Package Manager

This project uses `uv`. Use `uv` for all dependency and environment management:

```bash
uv run main.py          # Run the app
uv add <package>        # Add a dependency
uv run pytest           # Run tests (once pytest is added)
uv run pytest tests/test_foo.py::test_bar  # Run a single test
```

Python version is pinned to 3.14 via `.python-version`.

## Project Structure

- `main.py` — entry point, `main()` function
- `pyproject.toml` — project metadata and dependencies
