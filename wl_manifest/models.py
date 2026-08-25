"""The `wl.yaml` contract, and nothing that reads the lab.

This package exists so that the lab's repositories can depend on the manifest
schema without depending on the orchestrator's registry, which changes far more
often than the schema may. Ten registry entries sit at a lifecycle stage that
has a repository, not counting this package itself. The direction is one-way
and enforced in CI by a recursive scan of this package's source:
`wl_manifest` must never import `wl-orchestrator`.

`Declaration` and `RegistryEntry` are deliberately absent. They describe
entries in the lab's registry — a file only the orchestrator reads — and a
package that must not know about the registry cannot carry its types.

`wl.yaml` is authored by the package and is the only place that package's
identity, status and declarations are written.

Every model allows extra keys. That is deliberate and load-bearing: a manifest
written against a later `schema:` must parse under earlier code, or upgrading
the format becomes a simultaneous migration across fourteen repositories
(spec section 15.4). Unknown keys are reported as notes by `wl-check` here and
by `wl-orchestrator`'s `wlo validate` there,
never as errors, so a typo is still visible without being fatal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from wl_manifest.hosts import HostSelector

Lifecycle = Literal[
    "named", "declared", "scaffolded", "active", "deprecated", "archived"
]
PackageClass = Literal[
    "device", "pipeline", "application", "resource", "playbook",
    "experiment", "coordination",
]
Visibility = Literal["public", "private"]

# Lifecycle stages at which a repository is expected to exist.
STAGES_WITH_REPO: frozenset[str] = frozenset(
    {"scaffolded", "active", "deprecated", "archived"}
)


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ThirdPartyDep(_Tolerant):
    """One third-party dependency a package needs on the machines it runs on.

    `where` narrows the dependency to a subset of the package's own `runs_on`
    — Kilosort belongs on the preprocessing server and nowhere else.

    A `constraint` without a `why` is a fault (spec §6: the constraint is
    recoverable from code, the reasoning is not), but it is not a parse error.
    Enforcing it here raised out of `model_validate`, which `wl-orchestrator`'s
    `workspace.py` catches as an unreadable file — so one unexplained pin
    removed the whole package from every query, and `wlo stack` returned an
    empty stack for a machine that needed one. The rule now lives where
    findings live:
    `validate.V008` for the registry, `check.C003` for a single repository.
    """

    name: str
    constraint: str | None = None
    where: str | None = None
    why: str | None = None


class Requirement(_Tolerant):
    """One lab package this package depends on.

    Distinct from `third_party`, which records software the lab does not write.
    This records an edge inside the lab, and it is the only place such an edge
    is written down: the dependency itself lives in `pyproject.toml`, where no
    other repository can see it. `wl-preproc` has pinned `wl-sync` by commit
    since long before this field existed, and nothing outside that repository
    knew.

    `pinned_at` is the commit depended on, when there is one. An unpinned
    dependency is a fact, not a fault — but a pin without a `why` is, for the
    same reason a version constraint is (spec §6): the SHA is recoverable from
    `pyproject.toml`, and the reason it is frozen there is not. That fault is a
    finding, never a parse error — `validate.V010` across the registry,
    `check.C008` inside one repository. Raising instead was tried, and one
    unexplained pin silently emptied a workstation's software stack.

    `for` says what is consumed, and it is what makes the answer to "who breaks
    if I change this" actionable rather than merely true. It is spelled `for_`
    in Python because `for` is a keyword, the same accommodation `class` and
    `schema` already need.
    """

    name: str
    pinned_at: str | None = None
    for_: str | None = Field(default=None, alias="for")
    why: str | None = None


class Status(_Tolerant):
    """Where this package's build actually is. Authored only here."""

    phase: str | None = None
    next: str | None = None
    #: The commit this status describes: the tip of the branch this block was
    #: written from, at the time it was written. Not "the most recent merge
    #: commit" — the three existing uses each read the name differently, and
    #: half the lab's repositories fast-forward and so have no merge commit to
    #: point at. The tip is always defined, is what `git log -1` on that
    #: branch prints, and is the commit a reader needs in order to know what
    #: `phase` and `next` are relative to. A commit is named here rather than
    #: a date because a date cannot be checked and a commit can: a reader runs
    #: `git log --oneline <describes>..HEAD` and sees exactly what has
    #: happened since — a handful of commits and this status is probably
    #: still good, dozens and it is not.
    describes: str | None = None

    def unknown_keys(self) -> set[str]:
        """Top-level keys this code does not know about.

        Mirrors `PackageManifest.unknown_keys()`. `branch` and `updated` left
        this schema, renamed together as `describes` (spec section 15.5: the
        registry holds only what git cannot answer). `_Tolerant` still parses
        a manifest written against the old shape; this is what reports it.
        """
        return set(self.model_extra or {})


class PackageManifest(_Tolerant):
    """A package's `wl.yaml`."""

    schema_version: int = Field(alias="schema")
    slug: str
    klass: PackageClass = Field(alias="class")
    lifecycle: Lifecycle
    visibility: Visibility
    remote: str
    summary: str
    status: Status | None = None
    # Where this package's software is deployed.
    runs_on: list[str] = Field(default_factory=list)
    # Where this package is *worked on*, which is not the same thing. wl-shook
    # ships firmware and a board; nothing it produces runs on a lab host. But
    # its KiCad and its Python schematic generators run on a workstation, and
    # softrepo's catalog carries kicad.md precisely because someone designs
    # boards there. Without this field a device package contributes nothing to
    # any stack and that catalog entry has no declared source.
    builds_on: list[str] = Field(default_factory=list)
    third_party: list[ThirdPartyDep] = Field(default_factory=list)
    requires: list[Requirement] = Field(default_factory=list)
    superseded_by: str | None = None
    retention_reason: str | None = None

    @property
    def declared_hosts(self) -> tuple[str, ...]:
        """Every host selector this package declares, as written.

        `runs_on` and `builds_on` are different questions but the same
        namespace, and "which selectors does this manifest touch" was written
        out three times — twice in `wl-orchestrator`'s thirdparty.py and once
        in its validate.py. It is written here once, and `reach` is the parsed
        form of it.
        """
        return (*self.runs_on, *self.builds_on)

    @property
    def required_slugs(self) -> tuple[str, ...]:
        """Every lab package this one names, in the order it names them.

        The names as written. Resolving them through aliases needs the
        registry, so that belongs to `validate`, not here — this package must
        not learn about the lab.
        """
        return tuple(r.name for r in self.requires)

    @property
    def reach(self) -> tuple[HostSelector, ...]:
        """`declared_hosts`, parsed — with anything unparseable dropped.

        Tolerating bad input here is deliberate. `wl-orchestrator`'s `wlo validate`
        already reports
        every malformed selector as a V004 error against the package that wrote
        it, so nothing is hidden by skipping it. What is avoided is far worse:
        parsing unguarded meant one package writing `builds_on: [dwss]` turned
        every `wlo stack` query in the lab into an unhandled ValueError —
        including `stack serv` and `stack rig`, classes that package has nothing
        to do with. That contradicts that repository's validate.py contract that a broken
        registry stops the registry and not the lab, and workspace.py already
        takes the same care with a sibling it cannot stat. An advisory tool
        degrades; it does not take the lab down with the manifest that broke.
        """
        parsed: list[HostSelector] = []
        for text in self.declared_hosts:
            try:
                parsed.append(HostSelector.parse(text))
            except ValueError:
                continue  # reported as V004 by wl-orchestrator
        return tuple(parsed)

    def unknown_keys(self) -> set[str]:
        """Top-level keys this code does not know about.

        Reported as notes rather than errors, so a later schema still loads and
        a typo is still visible.

        `model_extra` is already exactly that set: pydantic v2 never puts a
        declared field — or its alias, so `class` and `schema` included — in
        there. Subtracting a hand-kept list of known keys was a no-op that also
        obliged anyone adding a field to remember to update it.
        """
        return set(self.model_extra or {})
