"""
MCP server for agent-safe Obsidian vault access.
Module-level _* functions accept explicit parameters so tests need no patching.
create_vault_server() returns a FastMCP instance ready to run or be imported.
"""

import os
import pathlib
import re
import shutil

from fastmcp import FastMCP

from .lint import linter_available, run_lint
from .paths import check_write_vault, resolve_safe, resolve_write_safe


# ── implementation functions ───────────────────────────────────────────────────

def _read_note(hvp: pathlib.Path, source: str) -> "str | dict":
    """
    Return the full markdown content of a note.
    source is in vault/relative/path.md format, as returned by search_notes.
    The full filesystem path is hvp / source.
    """
    path = resolve_safe(hvp, source)
    if isinstance(path, dict):
        return path
    if not path.exists():
        return {"error": "not_found", "source": source}
    if not path.is_file():
        return {"error": "not_a_file", "source": source}
    return path.read_text(encoding="utf-8")


def _list_notes(
    hvp: pathlib.Path, vault: str, folder: str = "", recursive: bool = True
) -> "list[str] | dict":
    """
    List note paths within a vault, optionally scoped to a subfolder.
    Returns paths in vault/relative/path.md format — the same format as the
    source field from search_notes — so results can be passed directly to
    read_note.
    Set recursive=False to list only the immediate folder (non-recursive).
    """
    base_source = f"{vault}/{folder}" if folder else vault
    base = resolve_safe(hvp, base_source)
    if isinstance(base, dict):
        return base
    if not base.exists():
        return {"error": "not_found", "source": base_source}
    if not base.is_dir():
        return {"error": "not_a_directory", "source": base_source}

    vault_root = hvp.resolve()
    glob_pattern = "**/*.md" if recursive else "*.md"
    return [
        p.relative_to(vault_root).as_posix()
        for p in sorted(base.glob(glob_pattern))
        if p.is_file()
    ]


def _create_note(
    hvp: pathlib.Path, wv: str, source: str, content: str, overwrite: bool = False
) -> dict:
    """
    Create a new note at source (vault/relative/path.md format).
    Refuses with a structured error if the target vault is not wv.
    Refuses to overwrite an existing file unless overwrite=True.
    Creates intermediate directories as needed.
    """
    err = check_write_vault(wv, source)
    if err:
        return err

    path = resolve_write_safe(hvp, wv, source)
    if isinstance(path, dict):
        return path

    existed = path.exists()
    if existed and not overwrite:
        return {"error": "already_exists", "source": source}

    vault_path = str(hvp) if hvp.parts else None
    lint_errors, lint_warnings = run_lint(content, vault_path)
    if lint_errors:
        return {"error": "validation_failed", "lint_errors": lint_errors, "lint_warnings": lint_warnings}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result = {"ok": True, "source": source, "action": "overwritten" if existed else "created"}
    if lint_warnings:
        result["lint_warnings"] = lint_warnings
    return result


def _update_note(
    hvp: pathlib.Path, wv: str, source: str, content: str, mode: str = "overwrite"
) -> dict:
    """
    Update an existing note. mode must be 'overwrite' (replace entire content)
    or 'append' (add content to the end of the file).
    Refuses with a structured error if the target vault is not wv.
    """
    err = check_write_vault(wv, source)
    if err:
        return err

    path = resolve_write_safe(hvp, wv, source)
    if isinstance(path, dict):
        return path

    if not path.exists():
        return {"error": "not_found", "source": source}

    if mode not in ("overwrite", "append"):
        return {"error": "invalid_mode", "mode": mode, "valid": ["overwrite", "append"]}

    vault_path = str(hvp) if hvp.parts else None
    lint_errors, lint_warnings = run_lint(content, vault_path)
    if lint_errors:
        return {"error": "validation_failed", "lint_errors": lint_errors, "lint_warnings": lint_warnings}

    if mode == "overwrite":
        path.write_text(content, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(content)

    result = {"ok": True, "source": source, "mode": mode}
    if lint_warnings:
        result["lint_warnings"] = lint_warnings
    return result


def _delete_note(hvp: pathlib.Path, wv: str, source: str) -> dict:
    """
    Move a note to the .trash folder at the vault root rather than deleting it
    permanently.  The directory structure within the vault is preserved under
    .trash so the file can be recovered if needed.
    Refuses with a structured error if the target vault is not wv.
    """
    err = check_write_vault(wv, source)
    if err:
        return err

    path = resolve_write_safe(hvp, wv, source)
    if isinstance(path, dict):
        return path

    if not path.exists():
        return {"error": "not_found", "source": source}

    vault_root = (hvp / wv).resolve()
    rel_within_vault = path.relative_to(vault_root)

    trash_path = vault_root / ".trash" / rel_within_vault
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(trash_path))

    return {
        "ok": True,
        "source": source,
        "trash": (pathlib.Path(wv) / ".trash" / rel_within_vault).as_posix(),
    }


def _rewrite_wikilinks(hvp: pathlib.Path, old_stem: str, new_stem: str) -> int:
    """
    Scan all .md files under hvp for wikilinks referencing old_stem and
    rewrite them to use new_stem.  Returns the count of files modified.
    Handles [[stem]], [[stem|alias]], ![[stem]], and ![[stem|alias]] forms.
    """
    pattern = re.compile(
        r"(!?\[\[)" + re.escape(old_stem) + r"(\|[^\]]*)?(\]\])"
    )
    replacement = r"\g<1>" + new_stem + r"\g<2>\g<3>"
    count = 0
    for md_file in hvp.rglob("*.md"):
        if not md_file.is_file():
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = pattern.sub(replacement, text)
        if new_text != text:
            md_file.write_text(new_text, encoding="utf-8")
            count += 1
    return count


def _move_note(
    hvp: pathlib.Path, wv: str, source: str, dest: str, create_dirs: bool = True
) -> dict:
    """
    Move a note from source to dest (both in vault/relative/path.md format).
    Both paths must be within the write vault.
    Fails if dest already exists — there is no overwrite option.
    If create_dirs=True, creates missing parent directories at the destination.
    After a successful move, rewrites wikilinks in all .md files that referenced
    the old filename so they point to the new filename.
    """
    # Both paths must be within the write vault
    err = check_write_vault(wv, source)
    if err:
        return err
    err = check_write_vault(wv, dest)
    if err:
        return err

    # Resolve both paths (handles symlinks) and confirm they stay within the write vault
    source_path = resolve_write_safe(hvp, wv, source)
    if isinstance(source_path, dict):
        return source_path
    dest_path = resolve_write_safe(hvp, wv, dest)
    if isinstance(dest_path, dict):
        return dest_path

    if not source_path.exists():
        return {"error": "not_found", "source": source}
    if dest_path.exists():
        return {"error": "already_exists", "destination": dest}

    if create_dirs:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(source_path), str(dest_path))

    old_stem = source_path.stem
    new_stem = dest_path.stem
    links_updated = _rewrite_wikilinks(hvp, old_stem, new_stem)

    return {
        "success": True,
        "source": source,
        "destination": dest,
        "links_updated": links_updated,
    }


def _lint_note(vault_path_str: "str | None", content: str) -> dict:
    """
    Pre-validate markdown content without writing it to disk.
    Returns a structured result with valid, errors, and warnings fields.
    Never raises.
    """
    if not linter_available():
        return {
            "valid": True,
            "errors": [],
            "warnings": [{"message": "mdlint-obsidian is not installed; validation skipped"}],
        }
    errors, warnings = run_lint(content, vault_path_str)
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ── server factory ─────────────────────────────────────────────────────────────

def create_vault_server(vault_path: "str | None" = None, write_vault: "str | None" = None) -> FastMCP:
    """
    Create and return a configured FastMCP instance.
    vault_path and write_vault default to HOST_VAULT_PATH and WRITE_VAULT env vars.
    """
    hvp = pathlib.Path(vault_path or os.getenv("HOST_VAULT_PATH", ""))
    wv = write_vault or os.getenv("WRITE_VAULT", "Claude")
    vault_path_str = str(hvp) if hvp.parts else None

    mcp = FastMCP("obsidian-mcp-guard")

    @mcp.tool()
    def read_note(source: str) -> "str | dict":
        """
        Return the full markdown content of a note.
        source is in vault/relative/path.md format, as returned by search_notes.
        The full filesystem path is HOST_VAULT_PATH / source.
        """
        return _read_note(hvp, source)

    @mcp.tool()
    def list_notes(vault: str, folder: str = "", recursive: bool = True) -> "list[str] | dict":
        """
        List note paths within a vault, optionally scoped to a subfolder.
        Returns paths in vault/relative/path.md format — the same format as the
        source field from search_notes — so results can be passed directly to
        read_note.
        Set recursive=False to list only the immediate folder (non-recursive).
        """
        return _list_notes(hvp, vault, folder, recursive)

    @mcp.tool()
    def create_note(source: str, content: str, overwrite: bool = False) -> dict:
        """
        Create a new note at source (vault/relative/path.md format).
        Refuses with a structured error if the target vault is not WRITE_VAULT.
        Refuses to overwrite an existing file unless overwrite=True.
        Creates intermediate directories as needed.
        """
        return _create_note(hvp, wv, source, content, overwrite)

    @mcp.tool()
    def update_note(source: str, content: str, mode: str = "overwrite") -> dict:
        """
        Update an existing note. mode must be 'overwrite' (replace entire content)
        or 'append' (add content to the end of the file).
        Refuses with a structured error if the target vault is not WRITE_VAULT.
        """
        return _update_note(hvp, wv, source, content, mode)

    @mcp.tool()
    def delete_note(source: str) -> dict:
        """
        Move a note to the .trash folder at the vault root rather than deleting it
        permanently.  The directory structure within the vault is preserved under
        .trash so the file can be recovered if needed.
        Refuses with a structured error if the target vault is not WRITE_VAULT.
        """
        return _delete_note(hvp, wv, source)

    @mcp.tool()
    def move_note(source_path: str, dest_path: str, create_dirs: bool = True) -> dict:
        """
        Move a note from source_path to dest_path (vault/relative/path.md format).
        Both paths must be within WRITE_VAULT.
        Fails if dest_path already exists — there is no overwrite option.
        If create_dirs=True (default), creates missing parent directories.
        After a successful move, wikilinks in all vault .md files that referenced
        the old filename are rewritten to use the new filename.
        Returns {"success": bool, "source": str, "destination": str, "links_updated": int}.
        """
        return _move_note(hvp, wv, source_path, dest_path, create_dirs)

    @mcp.tool()
    def lint_note(content: str) -> dict:
        """
        Pre-validate markdown content without writing it to disk.
        Returns {"valid": bool, "errors": [...], "warnings": [...]}.
        Use this to check content before calling create_note or update_note.
        """
        return _lint_note(vault_path_str, content)

    return mcp
