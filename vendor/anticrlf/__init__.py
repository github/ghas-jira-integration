""" a ``logging`` Formatter that escapes newline chars to avoid CRLF log injection (CWE-93)

Defines the class ``AntiCrlfFormatter``

"""
from __future__ import unicode_literals
import logging
import warnings

from anticrlf.types import SubstitutionMap


class LogFormatter(logging.Formatter):
    """logging Formatter to sanitize CRLF errors (CWE-93)

    This class is a drop-in replacement for ``logging.Formatter``, and has the
    exact same construction arguments. However, as a final step of formatting a
    log line, it escapes carriage returns (\r) and linefeeds (\n).

    By default, these are replaced with their escaped equivalents (see `Examples`_),
    but the ``replacements`` dictionary can be modified to change this behabior.

    Examples:
        ::

            import anticrlf

            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(anticrlf.LogFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

            logger = logging.getLogger(__name__)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("Example text with a newline\nhere")

        This results in::

            2017-02-03 08:43:52,557 - __main__ - INFO - Example text with a newline\nhere

        Whereas with the default ``Formatter``, it would be::

            2017-02-03 08:43:52,557 - __main__ - INFO - Example text with a newline
            here

        If you wanted newlines to be replaced with \x0A instead, you could::

            formatter = anticrlf.LogFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            formatter.replacements["\n"] = "\\x0A"  # Note the double backslash for literal!
            handler.setFormatter(formatter)

    """
    def __init__(self, fmt=None, datefmt=None):
        super(self.__class__, self).__init__(fmt=fmt, datefmt=datefmt)
        self.replacements = SubstitutionMap()  # defaults to mapping \n: \\n and \r: \\r

    def format(self, record):
        """calls logger.Formatter.format, then removes CR and LF from the resulting message before returning it"""
        if type(self.replacements) != SubstitutionMap:
            warnings.warn(UserWarning("replacements invalid: resetting to defaults"))
            self.replacements = SubstitutionMap()

        formatted_message = super(self.__class__, self).format(record)

        for repl in self.replacements:
            formatted_message = formatted_message.replace(repl, self.replacements[repl])

        return formatted_message
