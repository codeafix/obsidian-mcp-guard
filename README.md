# obsidian-mcp-guard

An MCP server for agent-safe Obsidian vault access. Provides read/write file tools with lint validation to prevent agents from writing malformed Obsidian markdown.

## Why this exists

Most Obsidian MCP servers give agents direct write access with no markdown validation. Those that route through the Obsidian REST API gain some input sanitisation, but none validate content against Obsidian's markdown rendering rules before writing. obsidian-mcp-guard fills this gap: all writes are validated against Obsidian's markdown rules before they touch the vault, and if the content would render incorrectly, the write is rejected with a structured error explaining exactly which rule was violated. Writes can also be constrained to a single configurable vault path, giving agents a designated space to create and manage content on behalf of the user while preventing accidental or runaway writes to other vaults on the same filesystem. Directory traversal attacks are blocked at the path resolution layer, so a misconfigured, misbehaving, or prompt-injected agent cannot escape the write vault by constructing paths like `Claude/../OtherVault/note.md`

## Features

- **Read/list/create/update/delete** notes via `HOST_VAULT_PATH` on the host filesystem
- **Lint validation** on all writes using [mdlint-obsidian](https://github.com/codeafix/mdlint-obsidian) — blocks writes that violate Obsidian markdown rules (unclosed wikilinks, raw HTML, standard-markdown links, etc.)
- **Write-vault isolation** — writes are constrained to a single configurable vault; directory-traversal attacks are blocked on both read and write paths
- **Composable** — `create_vault_server()` returns a `FastMCP` instance that can be mounted into a larger server via `import_server()`
- **Pre-validation tool** — `lint_note` lets agents check content before committing a write

## Installation

```bash
pip install obsidian-mcp-guard
```

For Claude Desktop users who don't want a manual install, `uvx` runs it directly with no setup:

```bash
uvx obsidian-mcp-guard
```

For local development:

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
/path/to/your/vaults/
    Claude/      ← write operations land here
    Work/        ← readable but not writable
    Personal/    ← readable but not writable
```

## Usage

### As a standalone stdio server

```bash
# via the installed CLI entry point
HOST_VAULT_PATH=/path/to/your/vaults obsidian-mcp-guard

# or via python -m
HOST_VAULT_PATH=/path/to/your/vaults python -m obsidian_mcp_guard
```

### Claude Desktop / Cursor config

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "uvx",
      "args": ["obsidian-mcp-guard"],
      "env": {
        "HOST_VAULT_PATH": "/path/to/your/vaults",
        "WRITE_VAULT": "Claude"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add obsidian -- uvx obsidian-mcp-guard
```

Pass environment variables with `-e`:

```bash
claude mcp add obsidian -e HOST_VAULT_PATH=/path/to/your/vaults -e WRITE_VAULT=Claude -- uvx obsidian-mcp-guard
```

### Mounted into another FastMCP server

```python
from contextlib import asynccontextmanager
from fastmcp import FastMCP
from obsidian_mcp_guard import create_vault_server

@asynccontextmanager
async def lifespan(app):
    await app.import_server(create_vault_server(
        vault_path="/path/to/your/vaults",
        write_vault="Claude"
    ))
    yield

mcp = FastMCP("my-agent", lifespan=lifespan)

@mcp.tool()
def search_notes(...):
    ...
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

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

## Related projects

- [mdlint-obsidian](https://github.com/codeafix/mdlint-obsidian) — the lint engine used to validate markdown against Obsidian's rendering rules

