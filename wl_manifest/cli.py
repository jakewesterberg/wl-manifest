"""The `wl-check` command: one repository, one manifest, one exit code."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wl_manifest.check import check_file, has_errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="wl-check",
        description="Check this repository's wl.yaml against the lab schema.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="the package directory, or the manifest itself (default: .)",
    )
    return check_path(Path(p.parse_args(argv).path))


def check_path(path: Path) -> int:
    """Report on one manifest and return its exit code.

    Separate from `main` so that `wlo check` can call it directly instead of
    keeping a second copy of this formatting. Two packages printing findings
    two ways is how the same output starts to differ depending on which command
    you happened to run.
    """
    manifest = path / "wl.yaml" if path.is_dir() else path
    if not manifest.exists():
        print(f"no wl.yaml at {manifest}", file=sys.stderr)
        return 2

    findings = check_file(manifest)
    for finding in findings:
        print(f"{finding.level:7} {finding.code}  {finding.message}")
    if not findings:
        print(f"{manifest}: no findings")
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
