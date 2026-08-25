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
    later = MINIMAL | {"publishes": [{"contract": "job-request", "version": 2}]}
    m = PackageManifest.model_validate(later)
    assert m.slug == "wl-preproc"
    assert m.unknown_keys() == {"publishes"}


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
