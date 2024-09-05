"""tests for anticrlf.LogFormatter"""
import pytest

from anticrlf import LogFormatter
from anticrlf.exception import *
from anticrlf.types import SubstitutionMap

from io import StringIO
import logging


@pytest.fixture()
def logbundle():
    logging.shutdown()

    strio = StringIO()

    formatter = LogFormatter('%(message)s')
    handler = logging.StreamHandler(strio)
    handler.setFormatter(formatter)

    logger = logging.getLogger('anticrlf_test')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    return logger, strio, formatter


def test_lf(logbundle):
    (logger, strio, formatter) = logbundle
    logger.info(u"Test\nitem")
    assert "Test\\nitem\n" == strio.getvalue()


def test_cr(logbundle):
    (logger, strio, formatter) = logbundle
    logger.info(u"Test\ritem")
    assert "Test\\ritem\n" == strio.getvalue()


def test_custom_sep(logbundle):
    (logger, strio, formatter) = logbundle
    formatter.replacements["\n"] = "^"
    logger.info(u"Test\n\nitem")
    assert "Test^^item\n" == strio.getvalue()


def test_dangerous_assign(logbundle):
    (logger, strio, formatter) = logbundle

    with pytest.raises(UnsafeSubstitutionError):
        formatter.replacements["\n"] = "\n"

    with pytest.raises(UnsafeSubstitutionError):
        formatter.replacements["\r"] = "\r"

    with pytest.raises(UnsafeSubstitutionError):
        formatter.replacements["\n"] = "\r"


def test_tricksy_bad_sub(logbundle):
    (logger, strio, formatter) = logbundle

    formatter.replacements = {"\n": "\n"}  # should be invalid, but it's a dict() not a SubstitutionMap

    with pytest.warns(UserWarning) as warnrec:
        logger.info(u"Test\n\nitem")
        exported_warnrec = warnrec

    assert str(exported_warnrec.pop().message) == "replacements invalid: resetting to defaults"

    assert type(formatter.replacements) == SubstitutionMap
    assert formatter.replacements["\n"] == "\\n"

    del formatter.replacements["\n"]
    assert formatter.replacements["\n"] == "\\n"  # should have restored defaults on del
