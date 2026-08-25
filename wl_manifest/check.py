"""Check one package's `wl.yaml`, and nothing outside that package.

This module is deliberately the narrowest thing in the repository. It reads the
manifest and, where a rule needs it, files the manifest points at inside the
same package directory — never another package, never the registry, never the
network. It imports no registry and no workspace, and never raises: every fault
it finds becomes a `CheckFinding`. That shape is what lets it run inside another
repository's CI, where failing on a neighbour's fault would be indefensible —
`wl-orchestrator`'s `wlo validate` cannot be used there for exactly that reason,
as its `cli/main.py` records.

The contract was once "reads a single file". C009 widened it: a checker that
cannot see whether a declared schema is still on disk cannot catch the likeliest
drift in `publishes`, and that check belongs in the repository where the file
lives. The invariant that matters is that it never reads another package.

The rules answer one question: is this manifest true about the repository it
sits in? Not "is the lab consistent" — that stays in `wl-orchestrator`'s
`validate.py`, which has the registry to compare against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from wl_manifest.hosts import HostSelector
from wl_manifest.models import STABILITIES, STAGES_WITH_REPO, PackageManifest


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


def check_file(path: Path) -> list[CheckFinding]:
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
    return check_mapping(data, root=path.parent)


def check_mapping(data: dict, root: Path | None = None) -> list[CheckFinding]:
    """Every rule, run over an already-parsed mapping.

    Rules run independently and none short-circuits another. A missing `why`
    used to abort parsing and take the whole manifest with it, which meant one
    unexplained version pin silently emptied a machine's entire stack. Here it
    is one finding among however many others are true at the same time.

    `root` is the package directory the manifest sits in — the only thing C009
    needs that the mapping itself cannot supply, since confirming a declared
    path exists means looking outside `data`. It is optional and defaults to
    `None` so this function stays callable on a bare mapping with no directory
    behind it, the way every rule above already is; C009 is silently skipped
    rather than guessing at a root it was never given.
    """
    findings: list[CheckFinding] = []
    findings += _schema_findings(data)
    findings += _reason_findings(data)
    findings += _requires_findings(data)
    findings += _selector_findings(data)
    findings += _lifecycle_findings(data)
    findings += _unknown_key_findings(data)
    findings += _status_findings(data)
    findings += _artifact_findings(data, root)
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


def _requires_findings(data: dict) -> list[CheckFinding]:
    """C008 — a lab dependency pinned to a commit with no reason given.

    The same rule as C003 and for the same reason: the SHA is recoverable from
    `pyproject.toml`, the reason it is frozen there is not. Whether the name
    resolves to a real package is deliberately NOT checked here — that needs
    the registry, and this module must run in a repository that has no access
    to it. `wl-orchestrator`'s `validate.V009` answers that question where it
    can be answered, and V010 mirrors this rule across the whole registry.
    """
    reqs = data.get("requires")
    if not isinstance(reqs, list):
        return []
    findings = []
    for req in reqs:
        if not isinstance(req, dict):
            continue
        if req.get("pinned_at") and not req.get("why"):
            name = req.get("name", "(unnamed)")
            findings.append(
                CheckFinding(
                    "error", "C008",
                    f"requires {name!r} pinned at {req['pinned_at']!r} with no `why`",
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


def _looks_repo_relative(at: str) -> bool:
    """A path this repository should contain, as opposed to a description.

    `docs/schemas/x.json` is checkable. `/data/sessions` is a runtime location
    on a server. `<runtime — the archive path…>` is prose in a field that
    usually holds a path, which is exactly what `at` is for when the artifact
    is not a file in the repository.

    This is a *scope* test, not a *safety* test: it decides whether `at` is
    the kind of value C009 should look at all, not whether the value it
    found is trustworthy. `../wl-preproc/x.json` passes it — not absolute, no
    `<` — which is exactly why `_escapes_root` exists as a second, separate
    check: looking like a repo path and staying inside the repo are different
    questions, and conflating them is what let `../wl-preproc/...` read a
    sibling package silently.
    """
    return not at.startswith("/") and "<" not in at


def _escapes_root(root: Path, at: str) -> bool:
    """Whether `root / at`, once resolved, falls outside `root`.

    A lexical count of `..` segments would catch `../wl-preproc/x.json`, but
    it would miss a `docs/link` that looks perfectly contained and is
    actually a symlink pointing somewhere else. Resolving both sides closes
    both holes at once: `Path.resolve()` collapses every `..` *and* follows
    every symlink it meets along the way, so a candidate that escapes either
    way ends up literally outside `root`'s own resolved form, and one
    `is_relative_to` comparison catches both.

    `root` always exists by the time this runs — it is `wl.yaml`'s own
    parent directory, or a caller's `tmp_path` — so resolving it is never
    surprising. The candidate need not exist yet; `resolve()` tolerates a
    non-existent tail the same way `os.path.normpath` would, which is what
    lets this run *before* the existence check rather than after it: an
    escaping path is wrong regardless of whether something happens to exist
    at the far end, and must be reported as escaping, not as merely missing.

    A handful of OS-level failures — a symlink loop, a path component the
    filesystem itself rejects (this module has already seen one real one:
    check_file's own embedded-null-byte case) — surface out of `resolve()`
    as `OSError`/`ValueError` rather than a clean answer either way. Between
    raising (forbidden everywhere in this module) and silently treating an
    unreadable path as safely contained, the finding that gets a human to
    look is the closer of the two to being right: "cannot confirm this stays
    inside the package" reads much closer to "does not" than to "does".
    """
    try:
        return not (root / at).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return True


def _artifact_findings(data: dict, root: Path | None) -> list[CheckFinding]:
    """C009-C012 — the `publishes` and `consumes` rules.

    C009 only looks at an `at` that looks like a path this repository should
    contain (`_looks_repo_relative`), and only when `root` is given — a
    manifest checked as a bare mapping, with no directory behind it, cannot
    have this rule guess one. Looking repo-relative is necessary but not
    sufficient: `_escapes_root` catches the case that slips past a purely
    lexical check, `../another-package/x.json`, which is neither absolute
    nor a placeholder and yet is not a path in this repository at all. C010
    and C011 need no filesystem access at all, so they run regardless of
    `root`. C012 exempts a `mirrors` entry: `wl-preproc` legitimately both
    re-exports `wl-sync`'s `syncbox-log-header` and reads sync box logs, so
    only the artifact's real owner — never a package that only mirrors it —
    can trigger "owns and consumes itself".
    """
    arts = data.get("publishes")
    findings: list[CheckFinding] = []
    owned: set[str] = set()

    if isinstance(arts, list):
        for art in arts:
            if not isinstance(art, dict):
                continue
            name = art.get("name", "(unnamed)")
            if not art.get("mirrors") and isinstance(art.get("name"), str):
                owned.add(art["name"])

            at = art.get("at")
            if (
                root is not None
                and isinstance(at, str)
                and at
                and _looks_repo_relative(at)
            ):
                if _escapes_root(root, at):
                    findings.append(
                        CheckFinding(
                            "error", "C009",
                            f"publishes {name!r} at {at!r}, which is outside "
                            "this package",
                        )
                    )
                elif not (root / at).exists():
                    findings.append(
                        CheckFinding(
                            "error", "C009",
                            f"publishes {name!r} at {at!r}, which is not in "
                            "this repository",
                        )
                    )

            if not art.get("what"):
                findings.append(
                    CheckFinding(
                        "error", "C010",
                        f"publishes {name!r} with no `what`; the shape is "
                        "recoverable by opening it, the meaning is not",
                    )
                )

            stability = art.get("stability")
            if stability not in STABILITIES:
                findings.append(
                    CheckFinding(
                        "error", "C011",
                        f"publishes {name!r} with stability {stability!r}; "
                        f"expected one of {sorted(STABILITIES)}",
                    )
                )

    taken = data.get("consumes")
    if isinstance(taken, list):
        for item in taken:
            if not isinstance(item, dict):
                continue
            if item.get("name") in owned:
                findings.append(
                    CheckFinding(
                        "error", "C012",
                        f"both owns and consumes {item['name']!r}; a package "
                        "cannot depend on itself. A mirrored artifact is "
                        "exempt — it is owned elsewhere",
                    )
                )
    return findings
