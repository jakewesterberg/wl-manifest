# tests/test_independence.py
"""The contract must not learn about the lab.

`wl-preproc` enforces the same rule against `wl-sync` with a CI step asserting
that `wl_sync.session` and `wl_sync.log` do not resolve inside `wl_preproc`.
This is that rule, pointing the other way.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

import wl_manifest

# On a developer machine that also has an editable wl-orchestrator checkout —
# this one included — `import wl_orchestrator` succeeds regardless of what
# wl_manifest does or does not import: the module is simply on sys.path. That
# makes the import-based test below meaningless in this environment, not
# merely inconvenient, so it is skipped here rather than left to fail for a
# reason that has nothing to do with wl_manifest. The CI job installs only
# `wl-manifest[dev]` into a bare environment, where wl_orchestrator genuinely
# is not importable, and is the real enforcement of this test. The
# source-scanning test below it has no such escape hatch and always runs.
_ORCHESTRATOR_INSTALLED = importlib.util.find_spec("wl_orchestrator") is not None


@pytest.mark.skipif(
    _ORCHESTRATOR_INSTALLED,
    reason=(
        "wl-orchestrator is installed in this environment (this machine has "
        "an editable checkout of it), so wl_orchestrator imports successfully "
        "no matter what wl_manifest does. CI installs wl-manifest alone into "
        "a bare environment, where this assertion is real; the source scan "
        "below (test_no_module_mentions_the_orchestrator) is unconditional "
        "and runs everywhere."
    ),
)
def test_wl_orchestrator_is_not_importable_from_here():
    with pytest.raises(ImportError):
        __import__("wl_orchestrator")


def test_no_module_mentions_the_orchestrator():
    root = pathlib.Path(wl_manifest.__file__).parent
    for module in root.rglob("*.py"):
        assert "wl_orchestrator" not in module.read_text(), module


def test_the_scan_reaches_a_nested_module(tmp_path, monkeypatch):
    """A subpackage must not be a blind spot.

    The scan used a flat `glob`, which stops at the top level. That was
    harmless while this package is flat and wrong the day it is not — and a
    direction check that quietly stops looking is worse than no check, because
    it reads as enforcement. `wl-orchestrator` closed the same hole in its own
    CI at 69b8fef; this repository had kept the flat form.
    """
    import wl_manifest

    root = pathlib.Path(wl_manifest.__file__).parent
    nested = root / "_scan_probe" / "deep.py"
    nested.parent.mkdir(exist_ok=True)
    nested.write_text("import wl_orchestrator\n")
    try:
        offenders = [p for p in root.rglob("*.py") if "wl_orchestrator" in p.read_text()]
        assert nested in offenders, "a nested violation must be visible to the scan"
        flat = [p for p in root.glob("*.py") if "wl_orchestrator" in p.read_text()]
        assert nested not in flat, "the flat form is what missed it"
    finally:
        nested.unlink()
        nested.parent.rmdir()
