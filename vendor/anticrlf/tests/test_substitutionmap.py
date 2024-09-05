import pytest

from anticrlf.types import SubstitutionMap
from anticrlf.exception import UnsafeSubstitutionError


def test_substitution_assign():
    smap = SubstitutionMap(key="value")
    assert type(smap) == SubstitutionMap
    assert smap['key'] == 'value'
    assert smap["\n"] == "\\n"
    assert smap["\r"] == "\\r"

    smap["key"] = "2value"
    assert type(smap) == SubstitutionMap
    assert smap['key'] == '2value'


def test_bad_substitution():
    with pytest.raises(UnsafeSubstitutionError):
        SubstitutionMap(x="hex")

    smap = SubstitutionMap(x="y")
    with pytest.raises(UnsafeSubstitutionError):
        smap['x'] = 'hex'

    smap = SubstitutionMap()

    smap["x"] = "r"
    with pytest.raises(UnsafeSubstitutionError):
        smap["r"] = "\\r"

    assert "\r" in smap.keys()
    with pytest.raises(UnsafeSubstitutionError):
        smap["x"] = "\r"  # any use of \r as a value should trigger this

    with pytest.raises(UnsafeSubstitutionError):
        smap["x"] = "\n"  # any use of \n as a value should trigger this


def test_delete():
    smap = SubstitutionMap()
    del smap["\n"]
    assert smap["\n"] == "\\n"

    smap["x"] = "y"
    del smap["x"]
    assert "x" not in smap
