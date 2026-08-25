"""The `wl-check` command — the one entry point every repository actually runs.

These tests exist because this module had none. The orchestrator exercises
`check_path` transitively through `wlo check`, so the code was covered *there*
while the package a repository installs shipped its command untested. A
dependency's own suite has to stand on its own: the whole point of this package
is that it is installed without `wl-orchestrator` anywhere nearby.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from wl_manifest.cli import check_path, main

GOOD = {
    "schema": 1,
    "slug": "wl-x",
    "class": "resource",
    "lifecycle": "active",
    "visibility": "private",
    "remote": "https://github.com/example/wl-x.git",
    "summary": "A package.",
    "runs_on": ["dws"],
    "status": {"phase": "building", "describes": "abc123"},
}


def _write(directory: Path, data: dict) -> Path:
    path = directory / "wl.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_a_clean_manifest_exits_zero(tmp_path, capsys):
    _write(tmp_path, GOOD)
    assert main([str(tmp_path)]) == 0
    assert "no findings" in capsys.readouterr().out


def test_an_error_exits_one_and_names_its_code(tmp_path, capsys):
    _write(tmp_path, {**GOOD, "runs_on": ["nonsense"]})
    assert main([str(tmp_path)]) == 1
    assert "C004" in capsys.readouterr().out


def test_notes_alone_still_exit_zero(tmp_path, capsys):
    """Forward tolerance reaches the exit code, not just the report."""
    _write(tmp_path, {**GOOD, "a_key_from_a_later_schema": 1})
    assert main([str(tmp_path)]) == 0
    assert "C006" in capsys.readouterr().out


def test_a_missing_manifest_exits_two_on_stderr(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "no wl.yaml" in captured.err
    assert captured.out == ""


def test_a_direct_file_path_is_accepted(tmp_path):
    path = _write(tmp_path, GOOD)
    assert main([str(path)]) == 0


def test_findings_go_to_stdout_so_a_ci_log_keeps_them(tmp_path, capsys):
    _write(tmp_path, {**GOOD, "runs_on": ["nonsense"]})
    main([str(tmp_path)])
    captured = capsys.readouterr()
    assert "C004" in captured.out
    assert captured.err == ""


def test_the_default_path_is_the_working_directory(tmp_path, capsys, monkeypatch):
    _write(tmp_path, GOOD)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0


def test_check_path_is_callable_without_argument_parsing(tmp_path):
    """`wlo check` calls this directly; it must not depend on argparse."""
    _write(tmp_path, GOOD)
    assert check_path(tmp_path) == 0


def test_a_manifest_that_cannot_be_parsed_is_reported_not_raised(tmp_path, capsys):
    (tmp_path / "wl.yaml").write_text("key: [unclosed\n")
    assert main([str(tmp_path)]) == 1
    assert "C001" in capsys.readouterr().out
