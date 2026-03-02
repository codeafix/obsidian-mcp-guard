"""Lint helpers wrapping mdlint-obsidian."""


def linter_available() -> bool:
    """Return True if mdlint-obsidian is importable."""
    try:
        import mdlint_obsidian  # noqa: F401
        return True
    except ImportError:
        return False


def run_lint(
    content: str, vault_path: "str | None" = None
) -> "tuple[list[dict], list[dict]]":
    """
    Validate markdown content with mdlint-obsidian.
    Returns (errors, warnings) as lists of serialisable dicts.
    Gracefully returns ([], []) if the package is not installed.
    """
    try:
        from mdlint_obsidian import validate, Severity
    except ImportError:
        return [], []
    kwargs = {"vault_path": vault_path} if vault_path else {}
    results = validate(content, **kwargs)
    errors = [
        {"rule": r.rule, "severity": "ERROR", "line": r.line, "message": r.message}
        for r in results if r.severity == Severity.ERROR
    ]
    warnings = [
        {"rule": r.rule, "severity": "WARNING", "line": r.line, "message": r.message}
        for r in results if r.severity == Severity.WARNING
    ]
    return errors, warnings
