# Contributing

## Dev environment

```bash
git clone https://github.com/codeafix/obsidian-mcp-guard.git
cd obsidian-mcp-guard
python3 -m venv .venv
source .venv/bin/activate
make install
```

## Running the tests

```bash
make test
```

All tests must pass before submitting a PR. Coverage must not drop below 90%.

## Adding a feature or fixing a bug

1. Fork the repo and create a branch: `git checkout -b my-feature`
2. Make your changes
3. Add or update tests in `tests/test_server.py`
4. Run the full test suite
5. Open a PR against `main` with a clear description of what changed and why

Keep PRs focused — one feature or fix per PR.

## Code style

- **Type hints** on all function signatures, including return types
- **Docstrings** on all public functions (the module-level `_*` implementation functions are considered internal and don't require them, but the functions registered as MCP tools must have descriptive docstrings — these become the tool descriptions visible to the agent)
- Implementation functions in `server.py` take explicit parameters rather than reading from globals, so tests never need to patch module-level state
- No external formatters are enforced, but follow the style of the existing code (4-space indent, single quotes for strings in logic, double quotes in docstrings)
