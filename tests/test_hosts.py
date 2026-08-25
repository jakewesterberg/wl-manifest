from __future__ import annotations

import pytest

from wl_manifest.hosts import HostSelector


def test_parses_a_bare_class():
    s = HostSelector.parse("serv")
    assert s.klass == "serv"
    assert s.role is None


def test_parses_a_class_and_role():
    # A rig is several machines: wl-rig-eye0, wl-rig-sglx0 (spec section 5.2).
    s = HostSelector.parse("rig/sglx")
    assert (s.klass, s.role) == ("rig", "sglx")


def test_rejects_an_unknown_class():
    with pytest.raises(ValueError, match="unknown host class"):
        HostSelector.parse("laptop")


def test_rejects_a_malformed_selector():
    with pytest.raises(ValueError, match="malformed"):
        HostSelector.parse("rig/sglx/extra")


def test_a_class_selector_selects_every_role_in_that_class():
    assert HostSelector.parse("rig").selects(HostSelector.parse("rig/sglx"))


def test_a_role_selector_does_not_select_the_bare_class():
    assert not HostSelector.parse("rig/sglx").selects(HostSelector.parse("rig"))


def test_a_role_selector_does_not_select_a_different_role():
    assert not HostSelector.parse("rig/eye").selects(HostSelector.parse("rig/sglx"))


def test_identical_selectors_select_each_other():
    assert HostSelector.parse("dws").selects(HostSelector.parse("dws"))


def test_overlap_is_symmetric_where_selection_is_not():
    rig = HostSelector.parse("rig")
    sglx = HostSelector.parse("rig/sglx")
    assert rig.selects(sglx) and not sglx.selects(rig)
    assert rig.overlaps(sglx) and sglx.overlaps(rig)
    assert not sglx.overlaps(HostSelector.parse("rig/eye"))
    assert not rig.overlaps(HostSelector.parse("serv"))
