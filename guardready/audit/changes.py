"""
ChangeSummary: the list of fields that one save changed or filled in.

The text goes into the details of a CREATE or UPDATE audit entry.

ENCAPSULATION: a sensitive value never even enters this object. Only the
field name is kept, so the value cannot leak into the audit log or a success
message by mistake.
"""

from datetime import date

from guards.dates import long_date

# How an empty value is written, for example: Rank from "blank" to "Head Guard".
BLANK = "blank"
# Written after the name of a sensitive field instead of its value.
HIDDEN = "(value hidden)"


def shown(value):
    """How a normal (not sensitive) value is written in the audit log."""
    if value is None or value == "":
        return BLANK
    if isinstance(value, date):
        return long_date(value)
    return str(value)


def same(old, new):
    """True if nothing really changed. An empty text and no value count as the same."""
    return (old if old is not None else "") == (new if new is not None else "")


class ChangeSummary:
    """The fields one save changed or filled in. Sensitive values are never kept."""

    def __init__(self):
        self._lines = []
        self._labels = []
        self._sensitive = False

    def __str__(self):
        if not self._lines:
            return "No changes"
        return "; ".join(self._lines)

    def __bool__(self):
        """True if at least one field changed or was filled in."""
        return bool(self._lines)

    @property
    def sensitive(self):
        """True if a sensitive field is listed. The audit entry copies this flag."""
        return self._sensitive

    @property
    def labels(self):
        """Only the field names, for success messages."""
        return list(self._labels)

    def changed(self, label, old, new, sensitive=False):
        """Note one field of an edit. Nothing is noted if the value stayed the same."""
        if same(old, new):
            return
        if sensitive:
            self._note_sensitive(label)
        else:
            self._note(label, f'{label} from "{shown(old)}" to "{shown(new)}"')

    def filled(self, label, value, sensitive=False):
        """Note one field of a new record. Empty fields are skipped."""
        if same(value, None):
            return
        if sensitive:
            self._note_sensitive(label)
        else:
            self._note(label, f'{label} "{shown(value)}"')

    def _note(self, label, line):
        self._labels.append(label)
        self._lines.append(line)

    def _note_sensitive(self, label):
        """Only the name is written. The value is never stored here."""
        self._note(label, f"{label} {HIDDEN}")
        self._sensitive = True
