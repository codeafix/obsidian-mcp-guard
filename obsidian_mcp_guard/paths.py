"""Path safety helpers — parameterized, no global state."""

import pathlib


def resolve_safe(host_vault_path: pathlib.Path, source: str) -> "pathlib.Path | dict":
    """
    Resolve host_vault_path / source and assert the result stays within
    host_vault_path.  Returns the resolved Path on success, or an error dict
    when source escapes the vault root via directory traversal.
    """
    if not host_vault_path.parts:
        return {"error": "host_vault_path_not_configured"}
    try:
        resolved = (host_vault_path / source).resolve()
        resolved.relative_to(host_vault_path.resolve())
        return resolved
    except ValueError:
        return {"error": "path_traversal", "source": source}


def check_write_vault(write_vault: str, source: str) -> "dict | None":
    """
    Return an error dict if the vault component (first path part) of source is
    not write_vault.  Return None when the write is permitted.
    This is a fast early-exit check on the raw path; resolve_write_safe performs
    the authoritative resolved check.
    """
    parts = pathlib.Path(source).parts
    vault = parts[0] if parts else ""
    if vault != write_vault:
        return {"error": "write_not_permitted", "vault": vault}
    return None


def resolve_write_safe(
    host_vault_path: pathlib.Path, write_vault: str, source: str
) -> "pathlib.Path | dict":
    """
    Resolve host_vault_path / source and assert the result stays within
    host_vault_path / write_vault.  Prevents directory-traversal attacks that
    use a leading write_vault component (e.g. 'Claude/../Other/note.md') to
    escape into a sibling vault that check_write_vault cannot detect on the
    unresolved path.
    """
    path = resolve_safe(host_vault_path, source)
    if isinstance(path, dict):
        return path
    write_root = (host_vault_path / write_vault).resolve()
    try:
        path.relative_to(write_root)
    except ValueError:
        return {"error": "write_not_permitted", "source": source}
    return path
