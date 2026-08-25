from __future__ import annotations

import pytest
from pydantic import ValidationError

from wl_manifest.models import PackageManifest, Status

MINIMAL = {
    "schema": 1,
    "slug": "wl-preproc",
    "class": "pipeline",
    "lifecycle": "active",
    "visibility": "private",
    "remote": "https://github.com/jakewesterberg/wl-preproc.git",
    "summary": "Session preprocessing to NWB.",
}


def test_manifest_parses_a_minimal_active_package():
    m = PackageManifest.model_validate(MINIMAL)
    assert m.slug == "wl-preproc"
    assert m.klass == "pipeline"
    assert m.schema_version == 1
    assert m.runs_on == []
    assert m.third_party == []


def test_manifest_tolerates_fields_from_a_later_schema():
    # Spec 15.4: the orchestrator's own schema is a fourteen-package contract.
    # A manifest written against schema 2 must still parse under schema 1 code,
    # or upgrading becomes a lockstep migration across every package.
    #
    # This used `publishes` as the stand-in for a field this schema version
    # doesn't know, until Task 1 (the two fields) made `publishes` a real,
    # validated field — so the placeholder moved to the name this same file
    # already uses for the concept elsewhere (see `a_later_field` below), and
    # what is being tested (a genuinely unknown key still parses and still
    # shows up in `unknown_keys()`) is unchanged.
    later = MINIMAL | {"a_later_field": [{"contract": "job-request", "version": 2}]}
    m = PackageManifest.model_validate(later)
    assert m.slug == "wl-preproc"
    assert m.unknown_keys() == {"a_later_field"}


def test_builds_on_is_separate_from_runs_on():
    # A device package deploys nothing to a lab host but is designed on one.
    m = PackageManifest.model_validate(
        MINIMAL | {"class": "device", "runs_on": [], "builds_on": ["dws"]}
    )
    assert m.runs_on == []
    assert m.builds_on == ["dws"]


def test_manifest_rejects_an_unknown_class():
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(MINIMAL | {"class": "gadget"})


def test_third_party_constraint_without_a_reason_no_longer_raises():
    # Spec 6: why is mandatory wherever a constraint is asserted, because the
    # shape is recoverable from code and the reasoning is not. This used to
    # be enforced by raising here — which propagated out of model_validate,
    # was caught by workspace.py as an unreadable file, and dropped the whole
    # package from every query. The requirement is unchanged; only where it
    # is enforced moved, to validate.V008 and check.C003.
    m = PackageManifest.model_validate(
        MINIMAL | {"third_party": [{"name": "datajoint", "constraint": ">=2.3,<3"}]}
    )
    assert m.third_party[0].constraint == ">=2.3,<3"
    assert m.third_party[0].why is None


def test_third_party_without_a_constraint_needs_no_reason():
    m = PackageManifest.model_validate(
        MINIMAL | {"third_party": [{"name": "spikeinterface"}]}
    )
    assert m.third_party[0].name == "spikeinterface"
    assert m.third_party[0].constraint is None


def test_declared_hosts_is_runs_on_then_builds_on():
    m = PackageManifest.model_validate(
        MINIMAL | {"runs_on": ["serv"], "builds_on": ["dws", "mws"]}
    )
    assert m.declared_hosts == ("serv", "dws", "mws")


def test_reach_parses_every_declared_selector():
    m = PackageManifest.model_validate(
        MINIMAL | {"runs_on": ["rig/sglx"], "builds_on": ["dws"]}
    )
    assert [str(s) for s in m.reach] == ["rig/sglx", "dws"]


def test_reach_drops_a_selector_that_does_not_parse():
    # validate reports it as V004; stack has to keep working. Parsing this
    # unguarded turned one typo into a traceback out of every stack query.
    m = PackageManifest.model_validate(MINIMAL | {"builds_on": ["dwss", "dws"]})
    assert [str(s) for s in m.reach] == ["dws"]


def test_status_still_parses_the_old_branch_and_updated_keys():
    # `branch` and `updated` left the schema on 2026-08-25, renamed together as
    # `describes` (docs/known-gaps.md, "Resolved"). This is spec 15.4's
    # forward-tolerance guarantee exercised by a real migration rather than a
    # hypothetical one: a manifest written under the old shape must still
    # parse, and the fields it carries that this code no longer knows about
    # must still be visible rather than silently swallowed.
    s = Status.model_validate(
        {
            "phase": "Phase 1c-4 (timebase)",
            "branch": "feat/phase-1c4-timebase",
            "next": "merge 1c-4, which completes Phase 1c",
            "updated": "2026-08-22",
        }
    )
    assert s.phase == "Phase 1c-4 (timebase)"
    assert s.unknown_keys() == {"branch", "updated"}


# --- requires: lab-internal dependencies -----------------------------------

REQ_MINIMAL = {
    "schema": 1,
    "slug": "wl-preproc",
    "class": "pipeline",
    "lifecycle": "active",
    "visibility": "private",
    "remote": "https://github.com/jakewesterberg/wl-preproc.git",
    "summary": "A package.",
}


def test_requires_defaults_to_empty():
    m = PackageManifest.model_validate(REQ_MINIMAL)
    assert m.requires == []


def test_a_requirement_records_the_pin_and_the_reason():
    m = PackageManifest.model_validate(REQ_MINIMAL | {
        "requires": [{
            "name": "wl-sync",
            "pinned_at": "abc1234",
            "for": "session identity and the log format",
            "why": "the sync box owns them; a local copy would drift silently",
        }],
    })
    r = m.requires[0]
    assert (r.name, r.pinned_at) == ("wl-sync", "abc1234")
    assert r.for_ == "session identity and the log format"
    assert "drift" in r.why


def test_a_requirement_needs_neither_pin_nor_reason():
    """An unpinned dependency is a fact, not a fault. V009 still resolves it."""
    m = PackageManifest.model_validate(REQ_MINIMAL | {
        "requires": [{"name": "wl-style"}],
    })
    assert m.requires[0].pinned_at is None
    assert m.requires[0].why is None


def test_an_unexplained_pin_does_not_raise():
    """Same doctrine as ThirdPartyDep: a fault becomes a finding, never a
    parse error. The raising version of that rule once dropped a whole package
    out of every query and emptied a workstation's software stack."""
    m = PackageManifest.model_validate(REQ_MINIMAL | {
        "requires": [{"name": "wl-sync", "pinned_at": "abc1234"}],
    })
    assert m.requires[0].why is None


def test_required_slugs_is_the_names_in_order():
    m = PackageManifest.model_validate(REQ_MINIMAL | {
        "requires": [{"name": "wl-sync"}, {"name": "wl-style"}],
    })
    assert m.required_slugs == ("wl-sync", "wl-style")


def test_unknown_keys_inside_a_requirement_are_tolerated():
    """Forward tolerance reaches nested models, or a later schema breaks here."""
    m = PackageManifest.model_validate(REQ_MINIMAL | {
        "requires": [{"name": "wl-sync", "a_later_field": 1}],
    })
    assert m.requires[0].name == "wl-sync"


# --- publishes / consumes: artifacts this package offers and builds on -----

from wl_manifest.models import STABILITIES, Artifact, Consumption

ART_MINIMAL = {
    "schema": 1, "slug": "wl-preproc", "class": "pipeline",
    "lifecycle": "active", "visibility": "private",
    "remote": "https://github.com/jakewesterberg/wl-preproc.git",
    "summary": "A package.",
}


def test_publishes_and_consumes_default_to_empty():
    m = PackageManifest.model_validate(ART_MINIMAL)
    assert m.publishes == [] and m.consumes == []


def test_an_artifact_records_what_it_is_and_where_it_lands():
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "session-manifest", "kind": "json-schema",
        "at": "docs/schemas/session_manifest.json", "stability": "stable",
        "what": "One record per recording session.",
    }]})
    a = m.publishes[0]
    assert (a.name, a.kind, a.stability) == (
        "session-manifest", "json-schema", "stable")
    assert a.at == "docs/schemas/session_manifest.json"
    assert a.mirrors is None and a.available_after is None


def test_a_runtime_artifact_needs_no_path():
    """The NWB session has no repo path; `at` must be optional."""
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "nwb-session", "kind": "nwb", "stability": "planned",
        "available_after": "ingest", "what": "Aligned streams on one clock.",
    }]})
    assert m.publishes[0].at is None
    assert m.publishes[0].available_after == "ingest"


def test_a_mirror_names_the_package_that_owns_the_artifact():
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "syncbox-log-header", "kind": "json-schema",
        "at": "docs/schemas/syncbox_log_header.json", "stability": "stable",
        "mirrors": "wl-sync", "what": "Re-exported from wl-sync.",
    }]})
    assert m.publishes[0].mirrors == "wl-sync"


def test_a_missing_what_does_not_raise():
    """Doctrine: a fault is a finding, never a parse error. C010 reports it."""
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "x", "kind": "json-schema", "stability": "stable",
    }]})
    assert m.publishes[0].what is None


def test_an_unknown_stability_does_not_raise():
    """C011 reports it. Raising would drop the whole manifest — the failure
    that once emptied a workstation's software stack."""
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "x", "kind": "nwb", "stability": "eventually", "what": "y",
    }]})
    assert m.publishes[0].stability == "eventually"


def test_consumption_records_the_name_and_the_reason():
    m = PackageManifest.model_validate(ART_MINIMAL | {"consumes": [
        {"name": "nwb-session", "why": "The scrubber replays aligned streams."},
    ]})
    assert m.consumes[0].name == "nwb-session"
    assert "scrubber" in m.consumes[0].why


def test_published_and_consumed_names_are_in_declared_order():
    m = PackageManifest.model_validate(ART_MINIMAL | {
        "publishes": [
            {"name": "b", "kind": "k", "stability": "stable", "what": "w"},
            {"name": "a", "kind": "k", "stability": "stable", "what": "w"},
        ],
        "consumes": [{"name": "z"}, {"name": "y"}],
    })
    assert m.published_names == ("b", "a")
    assert m.consumed_names == ("z", "y")


def test_owned_names_excludes_mirrors():
    """A mirror is not a publisher; only the owner appears in owned_names."""
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [
        {"name": "mine", "kind": "k", "stability": "stable", "what": "w"},
        {"name": "theirs", "kind": "k", "stability": "stable", "what": "w",
         "mirrors": "wl-sync"},
    ]})
    assert m.owned_names == ("mine",)


def test_the_stability_vocabulary_is_the_three_the_spec_names():
    assert STABILITIES == frozenset({"stable", "provisional", "planned"})


def test_unknown_keys_inside_an_artifact_are_tolerated():
    m = PackageManifest.model_validate(ART_MINIMAL | {"publishes": [{
        "name": "x", "kind": "k", "stability": "stable", "what": "w",
        "a_later_field": 1,
    }]})
    assert m.publishes[0].name == "x"
