# tests/test_check.py
from __future__ import annotations

import pathlib

import pytest

from wl_manifest.check import CheckFinding, check_file, check_mapping, has_errors

GOOD = {
    "schema": 1,
    "slug": "wl-example",
    # The brief's own fixture (and the adoption plan it's drawn from) uses
    # "library" here, but PackageClass in models.py has never included that
    # value — only device/pipeline/application/resource/playbook/experiment/
    # coordination are accepted (see wl_manifest/models.py). Adding
    # "library" to the schema is out of this task's scope (models.py is not
    # in Task 1's file list), so this fixture uses a class that is actually
    # valid today; the choice of *which* valid class is otherwise arbitrary.
    "class": "resource",
    "lifecycle": "active",
    "visibility": "private",
    "remote": "git@github.com:example/wl-example.git",
    "summary": "An example package.",
    "runs_on": ["dws", "serv/preproc"],
    "builds_on": ["dws"],
    "third_party": [{"name": "kilosort", "constraint": ">=4.0", "why": "spec §6"}],
    "status": {"phase": "building", "describes": "abc123"},
}


def codes(findings: list[CheckFinding]) -> list[str]:
    return [f.code for f in findings]


def test_a_good_manifest_produces_no_findings():
    assert check_mapping(GOOD) == []


def test_c002_reports_each_missing_required_field_without_raising():
    findings = check_mapping({"schema": 1, "slug": "wl-x"})
    assert "C002" in codes(findings)
    assert all(f.level == "error" for f in findings if f.code == "C002")


def test_c003_names_the_dependency_that_pins_without_a_reason():
    bad = {**GOOD, "third_party": [{"name": "kilosort", "constraint": ">=4.0"}]}
    findings = check_mapping(bad)
    assert "C003" in codes(findings)
    assert "kilosort" in " ".join(f.message for f in findings)


def test_c003_does_not_suppress_the_rest_of_the_manifest():
    """The blast-radius regression: one bad dep must not lose the manifest."""
    bad = {**GOOD, "third_party": [{"name": "kilosort", "constraint": ">=4.0"}],
           "runs_on": ["not-a-class"]}
    findings = check_mapping(bad)
    assert "C003" in codes(findings)
    assert "C004" in codes(findings)  # still checked, not short-circuited


def test_c004_reports_unknown_and_malformed_selectors():
    findings = check_mapping({**GOOD, "runs_on": ["dwss", "rig/", "serv/preproc"]})
    assert codes(findings).count("C004") == 2


def test_c005_rejects_a_lifecycle_that_implies_no_repository():
    findings = check_mapping({**GOOD, "lifecycle": "named"})
    assert "C005" in codes(findings)


def test_c006_reports_unknown_keys_as_notes_not_errors():
    findings = check_mapping({**GOOD, "quantum_flux": 7})
    note = next(f for f in findings if f.code == "C006")
    assert note.level == "note"
    assert "quantum_flux" in note.message
    assert not has_errors(findings)


def test_c006_is_not_suppressed_by_an_unrelated_c002():
    """Forward tolerance regression: a manifest can fail validation for one
    reason (a missing `summary`) and still need its unknown key surfaced —
    that is exactly the later-schema case C006 exists for, and it must not
    depend on the rest of the manifest validating cleanly first."""
    bad = {k: v for k, v in GOOD.items() if k != "summary"}
    bad["quantum_flux"] = 7
    findings = check_mapping(bad)
    assert "C002" in codes(findings)
    assert "C006" in codes(findings)


def test_c006_stringifies_non_string_keys_without_raising():
    """YAML 1.1's implicit typing (the 'Norway problem') means a top-level
    key is not always a string: a bare `on`/`off`/`yes`/`no`/`true`/`false`
    resolves to a bool, and a bare digit key to an int. Both are genuinely
    unknown keys and must be named in the C006 note rather than crashing
    `sorted()`/`.join()` on a mixed-type set."""
    bad = {**GOOD, True: "something", 7: "seven"}
    findings = check_mapping(bad)
    note = next(f for f in findings if f.code == "C006")
    assert "True" in note.message
    assert "7" in note.message


def test_c007_notes_a_missing_status():
    findings = check_mapping({k: v for k, v in GOOD.items() if k != "status"})
    assert "C007" in codes(findings)
    assert not has_errors(findings)


def test_c001_on_unparseable_yaml(tmp_path: pathlib.Path):
    p = tmp_path / "wl.yaml"
    p.write_text("key: [unclosed\n")
    findings = check_file(p)
    assert codes(findings) == ["C001"]


def test_c001_when_the_top_level_is_not_a_mapping(tmp_path: pathlib.Path):
    p = tmp_path / "wl.yaml"
    p.write_text("- just\n- a list\n")
    assert codes(check_file(p)) == ["C001"]


def test_c001_on_invalid_utf8(tmp_path: pathlib.Path):
    """Never-raises regression: `Path.read_text` raises `UnicodeDecodeError`
    on bad bytes, which is a `ValueError` and not an `OSError` — a narrower
    except clause here would let this one case through as a traceback
    instead of a finding."""
    p = tmp_path / "wl.yaml"
    p.write_bytes(b"key: \xff\xfe")
    findings = check_file(p)
    assert codes(findings) == ["C001"]


def test_c006_survives_yaml_implicit_typing_through_check_file(tmp_path: pathlib.Path):
    """The path a repository actually hits: PyYAML resolves a bare `on:`
    key to a boolean, not a string, before check_mapping ever sees it. This
    must still surface as a C006 note, not a traceback."""
    p = tmp_path / "wl.yaml"
    p.write_text(
        "schema: 1\n"
        "slug: wl-example\n"
        "class: resource\n"
        "lifecycle: active\n"
        "visibility: private\n"
        "remote: git@github.com:example/wl-example.git\n"
        "summary: An example package.\n"
        "on: something\n"
    )
    findings = check_file(p)
    note = next(f for f in findings if f.code == "C006")
    assert "True" in note.message


def test_check_file_reads_a_good_manifest(tmp_path: pathlib.Path):
    import yaml
    p = tmp_path / "wl.yaml"
    p.write_text(yaml.safe_dump(GOOD))
    assert check_file(p) == []


def test_check_never_raises_on_arbitrary_junk():
    for junk in [{}, {"schema": "not-an-int"}, {"third_party": "not-a-list"},
                 {"runs_on": 3}, {"status": "not-a-mapping"}]:
        assert isinstance(check_mapping(junk), list)




# --- C008: a lab dependency pinned without a reason -------------------------

def test_c008_names_the_package_pinned_without_a_reason():
    bad = {**GOOD, "requires": [{"name": "wl-sync", "pinned_at": "abc1234"}]}
    findings = check_mapping(bad)
    c008 = [f for f in findings if f.code == "C008"]
    assert len(c008) == 1
    assert c008[0].level == "error"
    assert "wl-sync" in c008[0].message and "abc1234" in c008[0].message


def test_c008_is_silent_when_the_pin_is_explained():
    ok = {**GOOD, "requires": [
        {"name": "wl-sync", "pinned_at": "abc1234", "why": "owns the log format"},
    ]}
    assert "C008" not in [f.code for f in check_mapping(ok)]


def test_c008_is_silent_on_an_unpinned_dependency():
    """An unpinned edge is a fact, not a fault."""
    assert "C008" not in [f.code for f in check_mapping({**GOOD, "requires": [{"name": "wl-style"}]})]


def test_c008_reports_every_offender_not_just_the_first():
    bad = {**GOOD, "requires": [
        {"name": "wl-sync", "pinned_at": "aaa"},
        {"name": "wl-style", "pinned_at": "bbb"},
    ]}
    assert [f.code for f in check_mapping(bad)].count("C008") == 2


def test_c008_survives_requires_being_junk():
    """The never-raises invariant reaches the new rule."""
    for junk in ["not-a-list", 3, None, [None], ["a string"], [{"no_name": 1, "pinned_at": "x"}]]:
        assert isinstance(check_mapping({**GOOD, "requires": junk}), list)


# --- C009-C012: the `publishes` and `consumes` rules -----------------------

ART_GOOD = {
    **GOOD,
    "publishes": [{
        "name": "session-manifest", "kind": "json-schema",
        "at": "docs/schemas/session_manifest.json", "stability": "stable",
        "what": "One record per session.",
    }],
}


def test_c009_reports_a_declared_path_that_is_not_there(tmp_path):
    findings = check_mapping(ART_GOOD, root=tmp_path)
    c009 = [f for f in findings if f.code == "C009"]
    assert len(c009) == 1 and c009[0].level == "error"
    assert "session_manifest.json" in c009[0].message


def test_c009_is_silent_when_the_file_exists(tmp_path):
    p = tmp_path / "docs" / "schemas"
    p.mkdir(parents=True)
    (p / "session_manifest.json").write_text("{}")
    assert "C009" not in [f.code for f in check_mapping(ART_GOOD, root=tmp_path)]


def test_c009_is_skipped_without_a_root():
    """check_mapping stays pure when no directory is given."""
    assert "C009" not in [f.code for f in check_mapping(ART_GOOD)]


def test_c009_does_not_check_a_runtime_description(tmp_path):
    data = {**GOOD, "publishes": [{
        "name": "nwb-session", "kind": "nwb", "stability": "planned",
        "at": "<runtime — the archive path in the session manifest>",
        "what": "Aligned streams.",
    }]}
    assert "C009" not in [f.code for f in check_mapping(data, root=tmp_path)]


def test_c009_does_not_check_an_absolute_path(tmp_path):
    data = {**GOOD, "publishes": [{
        "name": "x", "kind": "nwb", "stability": "stable",
        "at": "/data/sessions", "what": "y",
    }]}
    assert "C009" not in [f.code for f in check_mapping(data, root=tmp_path)]


def test_c010_reports_an_artifact_with_no_prose():
    data = {**GOOD, "publishes": [
        {"name": "x", "kind": "json-schema", "stability": "stable"},
    ]}
    c010 = [f for f in check_mapping(data) if f.code == "C010"]
    assert len(c010) == 1 and "x" in c010[0].message


def test_c011_reports_an_unknown_stability():
    data = {**GOOD, "publishes": [
        {"name": "x", "kind": "k", "stability": "eventually", "what": "w"},
    ]}
    c011 = [f for f in check_mapping(data) if f.code == "C011"]
    assert len(c011) == 1
    assert "eventually" in c011[0].message


def test_c011_reports_a_missing_stability():
    data = {**GOOD, "publishes": [{"name": "x", "kind": "k", "what": "w"}]}
    assert "C011" in [f.code for f in check_mapping(data)]


def test_c012_reports_owning_and_consuming_one_artifact():
    data = {**GOOD,
            "publishes": [{"name": "x", "kind": "k", "stability": "stable",
                           "what": "w"}],
            "consumes": [{"name": "x"}]}
    c012 = [f for f in check_mapping(data) if f.code == "C012"]
    assert len(c012) == 1 and "x" in c012[0].message


def test_c012_permits_consuming_an_artifact_this_package_only_mirrors():
    """wl-preproc mirrors syncbox-log-header and also reads sync box logs."""
    data = {**GOOD,
            "publishes": [{"name": "x", "kind": "k", "stability": "stable",
                           "what": "w", "mirrors": "wl-sync"}],
            "consumes": [{"name": "x"}]}
    assert "C012" not in [f.code for f in check_mapping(data)]


def test_the_new_rules_never_raise(tmp_path):
    junk = ["x", 3, None, [None], [{}], [{"name": None}], [[1]],
            [{"name": "a", "at": 7}], [{"name": "a", "stability": 3}]]
    for j in junk:
        assert isinstance(check_mapping({**GOOD, "publishes": j}, root=tmp_path), list)
        assert isinstance(check_mapping({**GOOD, "consumes": j}), list)


def test_check_file_supplies_the_package_directory(tmp_path):
    """The path rule must work through the real entry point, not only when a
    test passes root by hand."""
    import yaml
    (tmp_path / "wl.yaml").write_text(yaml.safe_dump(ART_GOOD))
    assert "C009" in [f.code for f in check_file(tmp_path / "wl.yaml")]
