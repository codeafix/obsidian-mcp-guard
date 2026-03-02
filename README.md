# obsidian-mcp-guard

An MCP server for agent-safe Obsidian vault access. Provides read/write file tools with lint validation to prevent agents from writing malformed Obsidian markdown.

## Features

- **Read/list/create/update/delete** notes via `HOST_VAULT_PATH` on the host filesystem
- **Lint validation** on all writes using [mdlint-obsidian](https://github.com/codeafix/mdlint-obsidian) — blocks writes that violate Obsidian markdown rules (unclosed wikilinks, raw HTML, standard-markdown links, etc.)
- **Write-vault isolation** — writes are constrained to a single configurable vault; directory-traversal attacks are blocked on both read and write paths
- **Composable** — `create_vault_server()` returns a `FastMCP` instance that can be mounted into a larger server via `import_server()`
- **Pre-validation tool** — `lint_note` lets agents check content before committing a write

## Installation

```bash
pip install git+https://github.com/your-org/obsidian-mcp-guard.git
```

Or install into a local venv for development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `HOST_VAULT_PATH` | *(required)* | Absolute path to the directory containing your vaults as subdirectories |
| `WRITE_VAULT` | `Claude` | Name of the only vault where write operations are permitted |

Example layout expected under `HOST_VAULT_PATH`:

```
/data/vaults/
    Claude/      ← write operations land here
    Work/        ← readable but not writable
    Personal/    ← readable but not writable
```

## Usage

### As a standalone stdio server

```bash
# via the installed CLI entry point
HOST_VAULT_PATH=/data/vaults obsidian-mcp-guard

# or via python -m
HOST_VAULT_PATH=/data/vaults python -m obsidian_mcp_guard
```

### Mounted into another FastMCP server

```python
from fastmcp import FastMCP
from obsidian_mcp_guard import create_vault_server

app = FastMCP("my-agent")
app.import_server(create_vault_server(vault_path="/data/vaults", write_vault="Claude"))
```

### Claude Desktop / Cursor config

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "obsidian-mcp-guard",
      "env": {
        "HOST_VAULT_PATH": "/data/vaults",
        "WRITE_VAULT": "Claude"
      }
    }
  }
}
```

## Tools

| Tool | Description |
|---|---|
| `read_note(source)` | Return full content of a note in `vault/path.md` format |
| `list_notes(vault, folder?, recursive?)` | List note paths within a vault or subfolder |
| `create_note(source, content, overwrite?)` | Create a note; blocked by lint errors |
| `update_note(source, content, mode?)` | Overwrite or append to a note; blocked by lint errors |
| `delete_note(source)` | Move a note to `.trash/` (recoverable) |
| `lint_note(content)` | Pre-validate content without writing; returns `{valid, errors, warnings}` |

## Development

```bash
pip install -e .
pip install pytest pytest-cov
pytest tests/ --cov=obsidian_mcp_guard
```
