from anticrlf.exception import UnsafeSubstitutionError


class SubstitutionMap(dict):
    """
    SubstitutionMap is a special-purpose ``dict`` for CRLF substitution maps

    ``SubstitutionMap`` is meant to provide error resistance when customizing replacements in
    the ``anticrlf`` log formatter.

    By default, an "empty" ``SubstitutionMap`` will map "\n" to "\\n" (linefeed to the string
    '\n') and "\r" to "\\r" (carriage return to the string '\r')

    Attempting to assign a value that contains any of the keys raises
    ``UnsafeSubstitutionError``, since setting a key is essentially claiming that key is an
    unsafe string

    Deleting either the "\n" or "\r" keys (e.g. using ``del``) resets them to their default
    values
    """
    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

        # if the constructor didn't provide substitutions for CR and LF, set up the defaults
        if "\n" not in self.keys():
            super(self.__class__, self).__setitem__("\n", "\\n")
        if "\r" not in self.keys():
            super(self.__class__, self).__setitem__("\r", "\\r")

        self.check_value()

    def __setitem__(self, key, value):
        self.check_value(key, value)
        super(self.__class__, self).__setitem__(key, value)

    def __delitem__(self, key):
        super(self.__class__, self).__delitem__(key)
        if "\n" not in self.keys():
            super(self.__class__, self).__setitem__("\n", "\\n")
        if "\r" not in self.keys():
            super(self.__class__, self).__setitem__("\r", "\\r")

    def check_value(self, key=None, value=None):
        subvalues = list(self.values())
        subkeys = list(self.keys())
        if value is not None and value not in subvalues:
            subvalues.append(value)
        if key is not None and key not in subkeys:
            subkeys.append(key)

        for val in subvalues:
            # if any value contains any key, throw an error; since the keys are unsafe strings, this prevents
            # a developer from accidentally setting a value that contains a string considered unsafe, at least
            # without trapping the errors -- can't stop determined sabotage...
            for key in subkeys:
                if key in val:
                    raise UnsafeSubstitutionError("Cannot assign a substitution that contains a value declared unsafe")
