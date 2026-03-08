"""Tests for obsidian_mcp_guard package."""
import json
import pathlib
import sys

import pytest
from unittest.mock import patch

from obsidian_mcp_guard.paths import resolve_safe, check_write_vault, resolve_write_safe
from obsidian_mcp_guard.lint import linter_available, run_lint
from obsidian_mcp_guard.server import (
    _read_note, _list_notes, _create_note, _update_note, _delete_note, _lint_note,
    _move_note, _rewrite_wikilinks,
    create_vault_server,
)

_WRITE_VAULT = "Claude"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def vault_root(tmp_path):
    """Temp directory acting as HOST_VAULT_PATH with two vaults."""
    (tmp_path / "Claude").mkdir()
    (tmp_path / "Other").mkdir()
    return tmp_path


# ── resolve_write_safe ────────────────────────────────────────────────────────

def test_resolve_write_safe_valid(vault_root):
    result = resolve_write_safe(vault_root, "Claude", "Claude/note.md")
    assert isinstance(result, pathlib.Path)
    assert result == (vault_root / "Claude" / "note.md").resolve()


def test_resolve_write_safe_traversal_to_sibling_vault(vault_root):
    """'Claude/../Other/note.md' resolves inside HOST_VAULT_PATH but outside WRITE_VAULT."""
    result = resolve_write_safe(vault_root, "Claude", "Claude/../Other/note.md")
    assert isinstance(result, dict)
    assert result["error"] == "write_not_permitted"


def test_resolve_write_safe_absolute_traversal(vault_root):
    result = resolve_write_safe(vault_root, "Claude", "../../../etc/passwd")
    assert isinstance(result, dict)
    assert result["error"] in ("path_traversal", "write_not_permitted")


# ── resolve_safe ──────────────────────────────────────────────────────────────

def test_resolve_safe_unconfigured():
    assert resolve_safe(pathlib.Path(""), "Claude/note.md") == {"error": "host_vault_path_not_configured"}


def test_resolve_safe_valid(vault_root):
    result = resolve_safe(vault_root, "Claude/note.md")
    assert isinstance(result, pathlib.Path)
    assert result == (vault_root / "Claude" / "note.md").resolve()


def test_resolve_safe_traversal(vault_root):
    result = resolve_safe(vault_root, "../../../etc/passwd")
    assert isinstance(result, dict)
    assert result["error"] == "path_traversal"
    assert result["source"] == "../../../etc/passwd"


# ── check_write_vault ─────────────────────────────────────────────────────────

def test_check_write_vault_permitted():
    assert check_write_vault("Claude", "Claude/note.md") is None


def test_check_write_vault_denied():
    result = check_write_vault("Claude", "Other/note.md")
    assert result == {"error": "write_not_permitted", "vault": "Other"}


def test_check_write_vault_empty_source():
    result = check_write_vault("Claude", "")
    assert result["error"] == "write_not_permitted"


# ── _read_note ────────────────────────────────────────────────────────────────

def test_read_note_success(vault_root):
    note = vault_root / "Claude" / "hello.md"
    note.write_text("# Hello\n\nWorld", encoding="utf-8")
    assert _read_note(vault_root, "Claude/hello.md") == "# Hello\n\nWorld"


def test_read_note_not_found(vault_root):
    assert _read_note(vault_root, "Claude/missing.md") == {
        "error": "not_found",
        "source": "Claude/missing.md",
    }


def test_read_note_is_directory(vault_root):
    result = _read_note(vault_root, "Claude")
    assert result == {"error": "not_a_file", "source": "Claude"}


def test_read_note_path_traversal(vault_root):
    result = _read_note(vault_root, "../../../etc/passwd")
    assert result["error"] == "path_traversal"


def test_read_note_no_vault_configured():
    assert _read_note(pathlib.Path(""), "Claude/note.md") == {"error": "host_vault_path_not_configured"}


# ── _list_notes ───────────────────────────────────────────────────────────────

def test_list_notes_recursive(vault_root):
    (vault_root / "Claude" / "a.md").write_text("a")
    (vault_root / "Claude" / "sub").mkdir()
    (vault_root / "Claude" / "sub" / "b.md").write_text("b")
    result = _list_notes(vault_root, "Claude")
    assert "Claude/a.md" in result
    assert "Claude/sub/b.md" in result


def test_list_notes_non_recursive(vault_root):
    (vault_root / "Claude" / "a.md").write_text("a")
    (vault_root / "Claude" / "sub").mkdir()
    (vault_root / "Claude" / "sub" / "b.md").write_text("b")
    result = _list_notes(vault_root, "Claude", recursive=False)
    assert "Claude/a.md" in result
    assert all("sub" not in p for p in result)


def test_list_notes_with_folder(vault_root):
    notes_dir = vault_root / "Claude" / "notes"
    notes_dir.mkdir()
    (notes_dir / "n.md").write_text("n")
    result = _list_notes(vault_root, "Claude", folder="notes")
    assert result == ["Claude/notes/n.md"]


def test_list_notes_not_found(vault_root):
    result = _list_notes(vault_root, "Claude", folder="nonexistent")
    assert result["error"] == "not_found"


def test_list_notes_not_a_directory(vault_root):
    (vault_root / "Claude" / "file.md").write_text("x")
    result = _list_notes(vault_root, "Claude", folder="file.md")
    assert result["error"] == "not_a_directory"


def test_list_notes_path_traversal(vault_root):
    result = _list_notes(vault_root, "../escape")
    assert result["error"] == "path_traversal"


def test_list_notes_returns_posix_paths(vault_root):
    (vault_root / "Claude" / "note.md").write_text("x")
    result = _list_notes(vault_root, "Claude")
    assert all("/" in p for p in result)


# ── _create_note ──────────────────────────────────────────────────────────────

def test_create_note_success(vault_root):
    result = _create_note(vault_root, "Claude", "Claude/new.md", "# New")
    assert result == {"ok": True, "source": "Claude/new.md", "action": "created"}
    assert (vault_root / "Claude" / "new.md").read_text() == "# New"


def test_create_note_creates_intermediate_dirs(vault_root):
    result = _create_note(vault_root, "Claude", "Claude/a/b/c.md", "deep")
    assert result["ok"] is True
    assert (vault_root / "Claude" / "a" / "b" / "c.md").read_text() == "deep"


def test_create_note_already_exists_no_overwrite(vault_root):
    (vault_root / "Claude" / "existing.md").write_text("old")
    result = _create_note(vault_root, "Claude", "Claude/existing.md", "new")
    assert result == {"error": "already_exists", "source": "Claude/existing.md"}
    assert (vault_root / "Claude" / "existing.md").read_text() == "old"


def test_create_note_overwrite(vault_root):
    (vault_root / "Claude" / "existing.md").write_text("old")
    result = _create_note(vault_root, "Claude", "Claude/existing.md", "new", overwrite=True)
    assert result == {"ok": True, "source": "Claude/existing.md", "action": "overwritten"}
    assert (vault_root / "Claude" / "existing.md").read_text() == "new"


def test_create_note_wrong_vault(vault_root):
    result = _create_note(vault_root, "Claude", "Other/note.md", "content")
    assert result["error"] == "write_not_permitted"
    assert result["vault"] == "Other"


def test_create_note_path_traversal(vault_root):
    result = _create_note(vault_root, "Claude", "Claude/../../../etc/evil.md", "x")
    assert result["error"] == "path_traversal"


# ── _update_note ──────────────────────────────────────────────────────────────

def test_update_note_overwrite(vault_root):
    (vault_root / "Claude" / "note.md").write_text("old")
    result = _update_note(vault_root, "Claude", "Claude/note.md", "new")
    assert result == {"ok": True, "source": "Claude/note.md", "mode": "overwrite"}
    assert (vault_root / "Claude" / "note.md").read_text() == "new"


def test_update_note_append(vault_root):
    (vault_root / "Claude" / "note.md").write_text("line1\n")
    result = _update_note(vault_root, "Claude", "Claude/note.md", "line2\n", mode="append")
    assert result == {"ok": True, "source": "Claude/note.md", "mode": "append"}
    assert (vault_root / "Claude" / "note.md").read_text() == "line1\nline2\n"


def test_update_note_not_found(vault_root):
    result = _update_note(vault_root, "Claude", "Claude/missing.md", "x")
    assert result == {"error": "not_found", "source": "Claude/missing.md"}


def test_update_note_invalid_mode(vault_root):
    (vault_root / "Claude" / "note.md").write_text("x")
    result = _update_note(vault_root, "Claude", "Claude/note.md", "y", mode="upsert")
    assert result["error"] == "invalid_mode"
    assert result["valid"] == ["overwrite", "append"]


def test_update_note_wrong_vault(vault_root):
    result = _update_note(vault_root, "Claude", "Other/note.md", "x")
    assert result["error"] == "write_not_permitted"


def test_update_note_path_traversal(vault_root):
    result = _update_note(vault_root, "Claude", "Claude/../../../etc/passwd", "x")
    assert result["error"] == "path_traversal"


# ── _delete_note ──────────────────────────────────────────────────────────────

def test_delete_note_moves_to_trash(vault_root):
    note = vault_root / "Claude" / "notes" / "del.md"
    note.parent.mkdir(parents=True)
    note.write_text("bye")
    result = _delete_note(vault_root, "Claude", "Claude/notes/del.md")
    assert result["ok"] is True
    assert result["source"] == "Claude/notes/del.md"
    assert result["trash"] == "Claude/.trash/notes/del.md"
    assert not note.exists()
    assert (vault_root / "Claude" / ".trash" / "notes" / "del.md").read_text() == "bye"


def test_delete_note_preserves_directory_structure(vault_root):
    (vault_root / "Claude" / "deep" / "nested").mkdir(parents=True)
    (vault_root / "Claude" / "deep" / "nested" / "note.md").write_text("x")
    _delete_note(vault_root, "Claude", "Claude/deep/nested/note.md")
    assert (vault_root / "Claude" / ".trash" / "deep" / "nested" / "note.md").exists()


def test_delete_note_not_found(vault_root):
    result = _delete_note(vault_root, "Claude", "Claude/ghost.md")
    assert result == {"error": "not_found", "source": "Claude/ghost.md"}


def test_delete_note_wrong_vault(vault_root):
    result = _delete_note(vault_root, "Claude", "Other/note.md")
    assert result["error"] == "write_not_permitted"


def test_delete_note_path_traversal(vault_root):
    result = _delete_note(vault_root, "Claude", "Claude/../../../etc/passwd")
    assert result["error"] == "path_traversal"


# ── write-vault traversal bypass tests ───────────────────────────────────────

def test_create_note_traversal_to_sibling_vault_blocked(vault_root):
    result = _create_note(vault_root, "Claude", "Claude/../Other/note.md", "content")
    assert result["error"] == "write_not_permitted"
    assert not (vault_root / "Other" / "note.md").exists()


def test_update_note_traversal_to_sibling_vault_blocked(vault_root):
    (vault_root / "Other" / "note.md").write_text("original")
    result = _update_note(vault_root, "Claude", "Claude/../Other/note.md", "evil")
    assert result["error"] == "write_not_permitted"
    assert (vault_root / "Other" / "note.md").read_text() == "original"


def test_delete_note_traversal_to_sibling_vault_blocked(vault_root):
    (vault_root / "Other" / "note.md").write_text("original")
    result = _delete_note(vault_root, "Claude", "Claude/../Other/note.md")
    assert result["error"] == "write_not_permitted"
    assert (vault_root / "Other" / "note.md").exists()


# ── lint validation ───────────────────────────────────────────────────────────

_ERR = [{"rule": "unclosed-wikilink", "severity": "ERROR", "line": 1, "message": "Wikilink not closed"}]
_WARN = [{"rule": "callout-invalid-type", "severity": "WARNING", "line": 1, "message": "Unknown callout type"}]
_LINK_WARN = [{"rule": "broken-link", "severity": "WARNING", "line": 1, "message": "Link does not resolve"}]


# _create_note — lint integration

def test_create_note_valid_content_no_lint_keys(vault_root):
    """Clean content produces no lint_warnings or lint_errors keys in the response."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], [])):
        result = _create_note(vault_root, "Claude", "Claude/clean.md", "# Clean note")
    assert result["ok"] is True
    assert "lint_warnings" not in result
    assert "lint_errors" not in result


def test_create_note_error_blocks_write(vault_root):
    """ERROR severity lint results abort the write; the file is not created."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=(_ERR, [])):
        result = _create_note(vault_root, "Claude", "Claude/bad.md", "[[unclosed")
    assert result["error"] == "validation_failed"
    assert result["lint_errors"] == _ERR
    assert result["lint_warnings"] == []
    assert not (vault_root / "Claude" / "bad.md").exists()


def test_create_note_warning_passes_with_warnings_in_response(vault_root):
    """WARNING severity lint results allow the write; warnings appear in the response."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], _WARN)):
        result = _create_note(vault_root, "Claude", "Claude/warn.md", "> [!BADTYPE]\n> body")
    assert result["ok"] is True
    assert result["lint_warnings"] == _WARN
    assert (vault_root / "Claude" / "warn.md").exists()


def test_create_note_broken_link_warning_does_not_block(vault_root):
    """Broken-link warnings (WARNING) must not block creates — the note may link forward."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], _LINK_WARN)):
        result = _create_note(vault_root, "Claude", "Claude/draft.md", "# Draft\n\n[[NotYetCreated]]")
    assert result["ok"] is True
    assert result["lint_warnings"] == _LINK_WARN
    assert (vault_root / "Claude" / "draft.md").exists()


def test_create_note_mixed_errors_and_warnings_blocks_write(vault_root):
    """When there are both ERRORs and WARNINGs, write is still blocked."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=(_ERR, _WARN)):
        result = _create_note(vault_root, "Claude", "Claude/mixed.md", "bad content")
    assert result["error"] == "validation_failed"
    assert result["lint_errors"] == _ERR
    assert result["lint_warnings"] == _WARN
    assert not (vault_root / "Claude" / "mixed.md").exists()


def test_create_note_lint_called_with_vault_path(vault_root):
    """vault_path is forwarded to run_lint for broken-link resolution."""
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], [])) as mock_lint:
        _create_note(vault_root, "Claude", "Claude/note.md", "# Note")
    mock_lint.assert_called_once_with("# Note", str(vault_root))


# _update_note — lint integration

def test_update_note_error_blocks_overwrite(vault_root):
    """ERROR severity results abort the overwrite; file content is preserved."""
    (vault_root / "Claude" / "note.md").write_text("original")
    with patch("obsidian_mcp_guard.server.run_lint", return_value=(_ERR, [])):
        result = _update_note(vault_root, "Claude", "Claude/note.md", "bad [[")
    assert result["error"] == "validation_failed"
    assert (vault_root / "Claude" / "note.md").read_text() == "original"


def test_update_note_warning_passes_with_warnings_in_response(vault_root):
    """WARNING results allow the overwrite; warnings appear in the response."""
    (vault_root / "Claude" / "note.md").write_text("original")
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], _WARN)):
        result = _update_note(vault_root, "Claude", "Claude/note.md", "new content")
    assert result["ok"] is True
    assert result["lint_warnings"] == _WARN
    assert (vault_root / "Claude" / "note.md").read_text() == "new content"


def test_update_note_error_blocks_append(vault_root):
    """ERROR results abort the append; file content is preserved."""
    (vault_root / "Claude" / "note.md").write_text("original\n")
    with patch("obsidian_mcp_guard.server.run_lint", return_value=(_ERR, [])):
        result = _update_note(vault_root, "Claude", "Claude/note.md", "bad [[", mode="append")
    assert result["error"] == "validation_failed"
    assert (vault_root / "Claude" / "note.md").read_text() == "original\n"


def test_update_note_warning_passes_append(vault_root):
    """WARNING results allow append; warnings appear in the response."""
    (vault_root / "Claude" / "note.md").write_text("line1\n")
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], _LINK_WARN)):
        result = _update_note(vault_root, "Claude", "Claude/note.md", "[[Forward]]\n", mode="append")
    assert result["ok"] is True
    assert result["lint_warnings"] == _LINK_WARN
    assert (vault_root / "Claude" / "note.md").read_text() == "line1\n[[Forward]]\n"


def test_update_note_invalid_mode_checked_before_lint(vault_root):
    """Invalid mode is rejected before lint runs."""
    (vault_root / "Claude" / "note.md").write_text("x")
    with patch("obsidian_mcp_guard.server.run_lint", return_value=([], [])) as mock_lint:
        result = _update_note(vault_root, "Claude", "Claude/note.md", "y", mode="upsert")
    assert result["error"] == "invalid_mode"
    mock_lint.assert_not_called()


# run_lint — unit tests

def test_run_lint_valid_content():
    """Valid plain markdown returns no errors or warnings."""
    errors, warnings = run_lint("# Hello\n\nThis is a note.")
    assert errors == []
    assert warnings == []


def test_run_lint_unclosed_wikilink_is_error():
    """An unclosed wikilink produces an ERROR."""
    errors, warnings = run_lint("[[unclosed")
    assert len(errors) == 1
    assert errors[0]["severity"] == "ERROR"
    assert errors[0]["rule"] == "unclosed-wikilink"
    assert isinstance(errors[0]["line"], int)
    assert isinstance(errors[0]["message"], str)


def test_run_lint_invalid_callout_is_warning():
    """An invalid callout type produces a WARNING, not an ERROR."""
    errors, warnings = run_lint("> [!BADTYPE]\n> content")
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "WARNING"
    assert warnings[0]["rule"] == "callout-invalid-type"


def test_run_lint_broken_link_is_warning(tmp_path):
    """A broken wikilink with a vault_path produces a WARNING, not an ERROR."""
    errors, warnings = run_lint("[[DoesNotExist]]", vault_path=str(tmp_path))
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "WARNING"
    assert warnings[0]["rule"] == "broken-link"


def test_run_lint_result_fields_are_serialisable():
    """LintError dicts contain only JSON-serialisable primitive types."""
    errors, warnings = run_lint("[[bad")
    json.dumps({"errors": errors, "warnings": warnings})  # must not raise


# run_lint — v0.2.0 rule unit tests (real linter, no mocking)

@pytest.mark.parametrize("content,expected_rule", [
    ("[click here](note.md)",          "std-internal-link"),
    ("![alt text](images/photo.png)",  "std-internal-image"),
    ("[text][ref]\n\n[ref]: http://x", "std-reference-link"),
    ("    indented code block",        "indented-code-block"),
    ("<div>some html</div>",           "raw-html"),
    ("***",                            "std-horizontal-rule"),
    ("___",                            "std-horizontal-rule"),
])
def test_run_lint_v02_rules_produce_errors(content, expected_rule):
    """Each new v0.2.0 standard-markdown rule produces at least one ERROR."""
    errors, warnings = run_lint(content)
    rules = [e["rule"] for e in errors]
    assert expected_rule in rules, (
        f"Expected rule {expected_rule!r} to fire as ERROR for content {content!r}, "
        f"got errors={errors}, warnings={warnings}"
    )
    assert all(e["severity"] == "ERROR" for e in errors if e["rule"] == expected_rule)


# End-to-end integration: real bad markdown must block _create_note / _update_note

@pytest.mark.parametrize("content,expected_rule", [
    ("[click here](note.md)",         "std-internal-link"),
    ("![alt](images/photo.png)",      "std-internal-image"),
    ("    indented code block",       "indented-code-block"),
    ("<div>raw html</div>",           "raw-html"),
    ("***",                           "std-horizontal-rule"),
])
def test_create_note_real_invalid_obsidian_markdown_is_blocked(vault_root, content, expected_rule):
    """_create_note rejects real content that violates v0.2.0 Obsidian rules."""
    result = _create_note(vault_root, "Claude", "Claude/bad.md", content)
    assert result.get("error") == "validation_failed", (
        f"Expected validation_failed for rule {expected_rule!r}, got {result!r}"
    )
    assert any(e["rule"] == expected_rule for e in result.get("lint_errors", [])), (
        f"Expected {expected_rule!r} in lint_errors, got {result.get('lint_errors')}"
    )
    assert not (vault_root / "Claude" / "bad.md").exists(), "File must not be written on validation failure"


@pytest.mark.parametrize("content,expected_rule", [
    ("[click here](note.md)",         "std-internal-link"),
    ("![alt](images/photo.png)",      "std-internal-image"),
    ("    indented code block",       "indented-code-block"),
    ("<div>raw html</div>",           "raw-html"),
    ("***",                           "std-horizontal-rule"),
])
def test_update_note_real_invalid_obsidian_markdown_is_blocked(vault_root, content, expected_rule):
    """_update_note rejects real content that violates v0.2.0 Obsidian rules; file unchanged."""
    note = vault_root / "Claude" / "note.md"
    note.write_text("original content")
    result = _update_note(vault_root, "Claude", "Claude/note.md", content)
    assert result.get("error") == "validation_failed", (
        f"Expected validation_failed for rule {expected_rule!r}, got {result!r}"
    )
    assert any(e["rule"] == expected_rule for e in result.get("lint_errors", [])), (
        f"Expected {expected_rule!r} in lint_errors, got {result.get('lint_errors')}"
    )
    assert note.read_text() == "original content", "File must not be modified on validation failure"


# ── _lint_note ────────────────────────────────────────────────────────────────

def test_lint_note_valid_content(vault_root):
    result = _lint_note(str(vault_root), "# Hello\n\nClean note.")
    assert result == {"valid": True, "errors": [], "warnings": []}


def test_lint_note_invalid_content_returns_false(vault_root):
    result = _lint_note(str(vault_root), "[click here](note.md)")
    assert result["valid"] is False
    assert any(e["rule"] == "std-internal-link" for e in result["errors"])


def test_lint_note_warning_only_is_valid(vault_root):
    result = _lint_note(str(vault_root), "> [!BADTYPE]\n> body")
    assert result["valid"] is True
    assert result["errors"] == []
    assert len(result["warnings"]) > 0


def test_lint_note_linter_unavailable():
    """When linter is not installed _lint_note returns valid=True with a skip warning."""
    with patch("obsidian_mcp_guard.server.linter_available", return_value=False):
        result = _lint_note(None, "any content")
    assert result["valid"] is True
    assert result["errors"] == []
    assert any("not installed" in w["message"] for w in result["warnings"])


# ── linter_available / run_lint — ImportError branches ───────────────────────

def test_linter_available_false_when_not_installed():
    """linter_available() returns False when mdlint_obsidian cannot be imported."""
    with patch.dict(sys.modules, {"mdlint_obsidian": None}):
        result = linter_available()
    assert result is False


def test_run_lint_returns_empty_when_not_installed():
    """run_lint() returns ([], []) gracefully when mdlint_obsidian cannot be imported."""
    with patch.dict(sys.modules, {"mdlint_obsidian": None}):
        errors, warnings = run_lint("[[bad content")
    assert errors == []
    assert warnings == []


# ── create_vault_server ───────────────────────────────────────────────────────

def test_create_vault_server_returns_fastmcp(vault_root):
    """create_vault_server() builds a FastMCP instance with all tools registered."""
    from fastmcp import FastMCP
    server = create_vault_server(vault_path=str(vault_root), write_vault="Claude")
    assert isinstance(server, FastMCP)


def test_create_vault_server_env_defaults(vault_root, monkeypatch):
    """create_vault_server() reads HOST_VAULT_PATH and WRITE_VAULT from env."""
    from fastmcp import FastMCP
    monkeypatch.setenv("HOST_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WRITE_VAULT", "Claude")
    server = create_vault_server()
    assert isinstance(server, FastMCP)


# ── _move_note ────────────────────────────────────────────────────────────────

def test_move_note_happy_path(vault_root):
    """Successfully moves a note and returns the expected dict."""
    (vault_root / "Claude" / "old.md").write_text("content")
    result = _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert result["success"] is True
    assert result["source"] == "Claude/old.md"
    assert result["destination"] == "Claude/new.md"
    assert isinstance(result["links_updated"], int)
    assert not (vault_root / "Claude" / "old.md").exists()
    assert (vault_root / "Claude" / "new.md").read_text() == "content"


def test_move_note_creates_parent_dirs(vault_root):
    """create_dirs=True (default) creates missing intermediate directories."""
    (vault_root / "Claude" / "note.md").write_text("x")
    result = _move_note(vault_root, "Claude", "Claude/note.md", "Claude/sub/dir/note.md")
    assert result["success"] is True
    assert (vault_root / "Claude" / "sub" / "dir" / "note.md").exists()


def test_move_note_source_traversal_rejected(vault_root):
    """.. traversal in source is rejected; Claude/../etc stays in hvp so fires write_not_permitted."""
    result = _move_note(vault_root, "Claude", "Claude/../etc/passwd", "Claude/dest.md")
    assert result["error"] == "write_not_permitted"


def test_move_note_dest_traversal_rejected(vault_root):
    """.. traversal in dest is rejected; source file is left untouched."""
    (vault_root / "Claude" / "note.md").write_text("x")
    result = _move_note(vault_root, "Claude", "Claude/note.md", "Claude/../etc/evil.md")
    assert result["error"] == "write_not_permitted"
    assert (vault_root / "Claude" / "note.md").exists()  # source untouched


def test_move_note_source_symlink_outside_vault_rejected(vault_root, tmp_path):
    """A symlink inside the vault that resolves outside the write vault is rejected."""
    outside = tmp_path / "secret.md"
    outside.write_text("secret")
    (vault_root / "Claude" / "link.md").symlink_to(outside)
    result = _move_note(vault_root, "Claude", "Claude/link.md", "Claude/dest.md")
    assert "error" in result
    assert not (vault_root / "Claude" / "dest.md").exists()


def test_move_note_dest_symlink_outside_vault_rejected(vault_root, tmp_path):
    """A dest path that resolves outside the write vault via symlink is rejected."""
    (vault_root / "Claude" / "source.md").write_text("content")
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (vault_root / "Claude" / "linked_dir").symlink_to(outside_dir)
    result = _move_note(vault_root, "Claude", "Claude/source.md", "Claude/linked_dir/dest.md")
    assert "error" in result
    assert (vault_root / "Claude" / "source.md").exists()  # source untouched


def test_move_note_dest_already_exists_fails(vault_root):
    """Moving to an already-existing destination is rejected; source is untouched."""
    (vault_root / "Claude" / "source.md").write_text("source content")
    (vault_root / "Claude" / "dest.md").write_text("dest content")
    result = _move_note(vault_root, "Claude", "Claude/source.md", "Claude/dest.md")
    assert result == {"error": "already_exists", "destination": "Claude/dest.md"}
    assert (vault_root / "Claude" / "source.md").read_text() == "source content"
    assert (vault_root / "Claude" / "dest.md").read_text() == "dest content"


def test_move_note_source_not_found(vault_root):
    result = _move_note(vault_root, "Claude", "Claude/missing.md", "Claude/dest.md")
    assert result == {"error": "not_found", "source": "Claude/missing.md"}


def test_move_note_wrong_vault_source(vault_root):
    result = _move_note(vault_root, "Claude", "Other/note.md", "Claude/dest.md")
    assert result["error"] == "write_not_permitted"


def test_move_note_wrong_vault_dest(vault_root):
    (vault_root / "Claude" / "note.md").write_text("x")
    result = _move_note(vault_root, "Claude", "Claude/note.md", "Other/dest.md")
    assert result["error"] == "write_not_permitted"
    assert (vault_root / "Claude" / "note.md").exists()


# ── _rewrite_wikilinks ────────────────────────────────────────────────────────

def test_move_note_rewrites_plain_wikilinks(vault_root):
    """[[old]] → [[new]] in files that reference the moved note."""
    (vault_root / "Claude" / "old.md").write_text("content")
    ref = vault_root / "Claude" / "ref.md"
    ref.write_text("See [[old]] for details.")
    result = _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert result["links_updated"] == 1
    assert ref.read_text() == "See [[new]] for details."


def test_move_note_rewrites_aliased_wikilinks(vault_root):
    """[[old|alias]] → [[new|alias]] after move."""
    (vault_root / "Claude" / "old.md").write_text("content")
    ref = vault_root / "Claude" / "ref.md"
    ref.write_text("Read [[old|the old note]] here.")
    _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert ref.read_text() == "Read [[new|the old note]] here."


def test_move_note_rewrites_transclusion_links(vault_root):
    """![[old]] → ![[new]] after move."""
    (vault_root / "Claude" / "old.md").write_text("content")
    ref = vault_root / "Claude" / "ref.md"
    ref.write_text("![[old]]")
    _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert ref.read_text() == "![[new]]"


def test_move_note_no_links_updated_when_none_reference_old(vault_root):
    """links_updated is 0 when no files reference the moved note."""
    (vault_root / "Claude" / "old.md").write_text("content")
    (vault_root / "Claude" / "unrelated.md").write_text("No links here.")
    result = _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert result["links_updated"] == 0


def test_move_note_rewrites_links_across_multiple_files(vault_root):
    """links_updated counts each file that was modified, not each link occurrence."""
    (vault_root / "Claude" / "old.md").write_text("content")
    (vault_root / "Claude" / "ref1.md").write_text("[[old]]")
    (vault_root / "Claude" / "ref2.md").write_text("[[old]] and [[old|alias]]")
    result = _move_note(vault_root, "Claude", "Claude/old.md", "Claude/new.md")
    assert result["links_updated"] == 2
