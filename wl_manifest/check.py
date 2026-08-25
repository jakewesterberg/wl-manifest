"""Check one package's `wl.yaml`, and nothing else.

This module is deliberately the narrowest thing in the repository. It reads a
single file, imports no registry and no workspace, and never raises: every
fault it finds becomes a `CheckFinding`. That shape is what lets it run inside
another repository's CI, where failing on a neighbour's fault would be
indefensible — `wl-orchestrator`'s `wlo validate` cannot be used there for
exactly that reason, as its `cli/main.py` records.

The rules answer one question: is this manifest true about the repository it
sits in? Not "is the lab consistent" — that stays in `wl-orchestrator`'s
`validate.py`, which has the registry to compare against.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml
from pydantic import ValidationError

from wl_manifest.hosts import HostSelector
from wl_manifest.models import STAGES_WITH_REPO, PackageManifest


@dataclass(frozen=True)
class CheckFinding:
    """One thing wrong with one manifest.

    Deliberately not `validate.Finding`: that carries a `slug` identifying
    which package in the registry a finding belongs to, and here there is only
    ever one package — the one whose directory we are standing in.
    """

    level: str
    code: str
    message: str


def has_errors(findings: list[CheckFinding]) -> bool:
    return any(f.level == "error" for f in findings)


def check_file(path: pathlib.Path) -> list[CheckFinding]:
    """Read and check one manifest. Never raises.

    `Path.read_text` decodes as it reads, so a manifest that is not valid
    UTF-8 fails with `UnicodeDecodeError` — a `ValueError` subclass, not an
    `OSError`, so it needs its own arm here rather than falling under the
    same `except` as a missing or unreadable file. Without it, the one input
    likeliest to be garbled — a bad copy from another encoding, a stray
    binary paste — would be the one case that broke this module's central
    promise instead of becoming a finding like everything else.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [CheckFinding("error", "C001", f"cannot read {path}: {exc}")]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [CheckFinding("error", "C001", f"{path} is not valid YAML: {exc}")]
    if not isinstance(data, dict):
        kind = type(data).__name__
        return [
            CheckFinding(
                "error", "C001",
                f"{path} must be a mapping at the top level, found {kind}",
            )
        ]
    return check_mapping(data)


def check_mapping(data: dict) -> list[CheckFinding]:
    """Every rule, run over an already-parsed mapping.

    Rules run independently and none short-circuits another. A missing `why`
    used to abort parsing and take the whole manifest with it, which meant one
    unexplained version pin silently emptied a machine's entire stack. Here it
    is one finding among however many others are true at the same time.
    """
    findings: list[CheckFinding] = []
    findings += _schema_findings(data)
    findings += _reason_findings(data)
    findings += _selector_findings(data)
    findings += _lifecycle_findings(data)
    findings += _unknown_key_findings(data)
    findings += _status_findings(data)
    return findings


def _schema_findings(data: dict) -> list[CheckFinding]:
    try:
        PackageManifest.model_validate(data)
    except ValidationError as exc:
        return [
            CheckFinding(
                "error", "C002",
                f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}",
            )
            for err in exc.errors()
        ]
    return []


def _reason_findings(data: dict) -> list[CheckFinding]:
    """Spec §6: the constraint is recoverable from code, the reasoning is not."""
    deps = data.get("third_party")
    if not isinstance(deps, list):
        return []
    findings = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        if dep.get("constraint") and not dep.get("why"):
            name = dep.get("name", "(unnamed)")
            findings.append(
                CheckFinding(
                    "error", "C003",
                    f"third_party {name!r} pins {dep['constraint']!r} with no `why`",
                )
            )
    return findings


def _selector_findings(data: dict) -> list[CheckFinding]:
    findings = []
    for field in ("runs_on", "builds_on"):
        values = data.get(field)
        if not isinstance(values, list):
            continue
        for text in values:
            if not isinstance(text, str):
                continue
            try:
                HostSelector.parse(text)
            except ValueError as exc:
                findings.append(CheckFinding("error", "C004", f"{field}: {exc}"))
    return findings


def _lifecycle_findings(data: dict) -> list[CheckFinding]:
    """A manifest only exists inside a repository, so it must say so.

    Catching this needs no registry: the file's own presence is the evidence
    that contradicts a `named` or `declared` lifecycle.
    """
    lifecycle = data.get("lifecycle")
    if isinstance(lifecycle, str) and lifecycle not in STAGES_WITH_REPO:
        return [
            CheckFinding(
                "error", "C005",
                f"lifecycle is {lifecycle!r}, but this manifest sits in a "
                f"repository; expected one of {sorted(STAGES_WITH_REPO)}",
            )
        ]
    return []


def _known_manifest_keys() -> frozenset[str]:
    """Every top-level key `PackageManifest` recognizes, by field name or alias.

    A manifest is authored with the aliases (`schema`, `class`) but
    `populate_by_name=True` also accepts the underlying field names
    (`schema_version`, `klass`), so both count as known — a key is unknown
    only if it matches neither.
    """
    known: set[str] = set()
    for name, field in PackageManifest.model_fields.items():
        known.add(name)
        if field.alias:
            known.add(field.alias)
    return frozenset(known)


def _unknown_key_findings(data: dict) -> list[CheckFinding]:
    """Note-level, computed from the raw mapping rather than a validated model.

    This used to build on `PackageManifest.model_validate(data).unknown_keys()`
    and return `[]` whenever validation failed — which meant one unrelated
    C002 (a missing `summary`, say) silently ate the C006 note about a typo
    sitting right next to it. That defeats forward tolerance exactly where it
    matters most: a manifest written against a later schema, with a field
    this code doesn't know is required yet, is precisely a mapping that both
    fails validation *and* carries a key worth surfacing. Reading `data`
    directly needs no successful validation, so the two findings are
    independent again — do not "simplify" this back to calling
    `model_validate` for convenience; that reintroduces the suppression.
    `PackageManifest.unknown_keys()` itself is unaffected and stays correct
    for callers who already have a validated model in hand.
    """
    unknown = set(data) - _known_manifest_keys()
    if not unknown:
        return []
    # YAML 1.1's implicit typing means a top-level key need not be a string:
    # a bare `on`, `off`, `yes`, `no`, `true`, or `false` key resolves to a
    # bool, and a bare digit key to an int (PyYAML's "Norway problem"). Such
    # a key is still a genuinely unknown key and still belongs in this note
    # — but `sorted()` cannot order a `str` against a `bool`/`int`, and
    # `str.join()` cannot render one at all, so every key is stringified
    # before either runs. Sorting or joining `unknown` directly is what
    # turned an unrelated `on:` key into a crash instead of a finding.
    return [
        CheckFinding(
            "note", "C006",
            f"keys this version does not know: "
            f"{', '.join(sorted(str(k) for k in unknown))}",
        )
    ]


def _status_findings(data: dict) -> list[CheckFinding]:
    status = data.get("status")
    if status is None:
        return [CheckFinding("note", "C007", "no `status` block")]
    if isinstance(status, dict) and not status.get("describes"):
        return [
            CheckFinding(
                "note", "C007",
                "`status` has no `describes`, so nothing says which commit it "
                "was true at",
            )
        ]
    return []
