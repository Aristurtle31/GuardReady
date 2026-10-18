"""
The base classes of every report in GuardReady (Stage 4).

Report is the one report base class: the compliance reports (compliance.py)
and the guard reports (guard_reports.py) all extend it. Every table in a
report extends ReportSection.

OOP in this file
- ABSTRACTION: Report and ReportSection are abstract base classes.
- POLYMORPHISM: each report overrides title(), sections() and _request_rows().
  Each table overrides columns() and _collect().
- Shared steps stay here and call those methods: build() runs each table once,
  header_rows() and log_details() describe the report, and write_csv() is the
  one CSV writer for every report.
- COMPOSITION: a report owns the tables (sections) it builds.
- ENCAPSULATION: a report keeps its data in protected attributes with
  read-only properties, and gets its number only once, from its REPORT entry.
"""

import csv
from abc import ABC, abstractmethod

from django.db.models import Q
from django.utils.text import slugify

from deployment.models import Assignment
from guards.constants import LESP_LICENSE, NOT_ON_FILE
from guards.dates import long_date, long_datetime

from .constants import (
    FORMULA_STARTS,
    NAME_NOT_ON_FILE,
    REPORT_NUMBER_DIGITS,
    REPORT_NUMBER_PREFIX,
    STILL_POSTED,
)


def person_name(user):
    """A user's full name, never the username. Client reports must not show usernames."""
    return user.get_full_name().strip() or NAME_NOT_ON_FILE


def safe_cell(value):
    """
    One CSV cell. A spreadsheet runs text that starts with =, +, -, @ or a tab
    as a formula, so that text gets a ' in front and stays plain text.
    """
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# Sections: one table each
# ---------------------------------------------------------------------------


class ReportSection(ABC):
    """ABSTRACTION: one table of a report. Each subclass picks its own columns and rows."""

    KEY = ""
    TITLE = ""
    NOTE = ""

    def __init__(self, report):
        self._report = report
        self._rows = []
        self._guard_ids = set()
        self._built = False

    def __str__(self):
        return f"{self.TITLE}: {len(self._rows)} rows"

    @abstractmethod
    def columns(self):
        """The column headings, in print order."""

    @abstractmethod
    def _collect(self):
        """Run the query and return the rows. Each row is a list of printable values."""

    def build(self):
        """Run the query once. Calling build() again does nothing."""
        if not self._built:
            self._rows = self._collect()
            self._built = True
        return self

    @property
    def title(self):
        return self.TITLE

    @property
    def rows(self):
        return list(self._rows)

    @property
    def row_count(self):
        return len(self._rows)

    @property
    def guard_ids(self):
        """The guards this table names. Counted for the REPORT audit entry."""
        return set(self._guard_ids)

    # --- Helpers the subclasses share ---

    def _guard_row(self, guard, *cells):
        """A row that names a guard. The guard is counted for the audit log."""
        self._guard_ids.add(guard.pk)
        return list(cells)

    def _lesp_cells(self, guard):
        """The LESP number and expiry date, or Not on file."""
        lesp = guard.get_credential(LESP_LICENSE)
        if lesp is None:
            return NOT_ON_FILE, NOT_ON_FILE
        return lesp.number, long_date(lesp.expires)

    def _postings(self):
        """Every assignment that overlaps the report period, at every site."""
        start, end = self._report.period_start, self._report.period_end
        return (
            Assignment.objects.filter(start_date__lte=end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
            .select_related("guard", "post__site")
            .order_by("start_date", "guard__last_name", "guard__first_name", "id")
        )

    @staticmethod
    def _end_text(assignment):
        """The last day of a posting, or Still posted."""
        if assignment.end_date is None:
            return STILL_POSTED
        return long_date(assignment.end_date)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class Report(ABC):
    """ABSTRACTION: a report built from GuardReady's records, for one period, made of tables."""

    # The target type of its REPORT audit entry, and whether that entry is sensitive.
    TARGET_TYPE = ""
    SENSITIVE = False
    # How the counts in the REPORT entry read: "Rows printed: 12".
    OUTPUT = "printed"

    def __init__(self, period_start, period_end, prepared_by):
        self._period_start = period_start
        self._period_end = period_end
        self._prepared_by = prepared_by
        self._sections = []
        self._entry_id = None
        self._generated_at = None

    def __str__(self):
        return f"{self.title()} {self.number}".strip()

    # --- What every report overrides (POLYMORPHISM) ---

    @classmethod
    @abstractmethod
    def title(cls):
        """The title at the top of the report."""

    @classmethod
    @abstractmethod
    def sections(cls):
        """The section classes this report may build, in order."""

    @abstractmethod
    def _request_rows(self):
        """What was asked for (the period, the guard or the filters) as label and value pairs."""

    def _chosen_sections(self):
        """The section classes to build. All of them, unless a report lets the user untick some."""
        return self.sections()

    def _file_label(self):
        """The name of the CSV file after the report number. A report can make it more exact."""
        return slugify(self.title())

    # --- Building and numbering, the same for every report ---

    def build(self):
        """Run every chosen section once, in order. Returns the report."""
        self._sections = [section_class(self).build() for section_class in self._chosen_sections()]
        return self

    def assign_number(self, entry):
        """ENCAPSULATION: the report number comes from its REPORT audit entry, and only once."""
        if self._entry_id is not None:
            raise ValueError("This report already has a number.")
        self._entry_id = entry.pk
        self._generated_at = entry.timestamp

    # --- Read-only values for the pages, the CSV file and the audit log ---

    @property
    def number(self):
        """Like GR-RPT-000123. Empty until assign_number() runs."""
        if self._entry_id is None:
            return ""
        return f"{REPORT_NUMBER_PREFIX}{self._entry_id:0{REPORT_NUMBER_DIGITS}d}"

    @property
    def period_start(self):
        return self._period_start

    @property
    def period_end(self):
        return self._period_end

    @property
    def built_sections(self):
        return list(self._sections)

    @property
    def prepared_by_name(self):
        return person_name(self._prepared_by)

    def period_text(self):
        return f"{long_date(self._period_start)} to {long_date(self._period_end)}"

    def header_rows(self):
        """Everything shown under the title."""
        return [
            ("Report number", self.number),
            ("Date and time generated", f"{long_datetime(self._generated_at)} (Philippine time)"),
            ("Generated by", self.prepared_by_name),
        ] + self._request_rows()

    def guards_printed(self):
        """How many different guards are named anywhere in the report."""
        guard_ids = set()
        for section in self._sections:
            guard_ids |= section.guard_ids
        return len(guard_ids)

    def rows_printed(self):
        return sum(section.row_count for section in self._sections)

    def log_details(self):
        """One line for the REPORT audit entry: what was asked for, the sections, and the counts."""
        parts = [f"Report: {self.title()}"]
        parts += [f"{label}: {value}" for label, value in self._request_rows()]
        parts.append("Sections: " + "; ".join(section.title for section in self._sections))
        parts.append(f"Guards {self.OUTPUT}: {self.guards_printed()}")
        parts.append(f"Rows {self.OUTPUT}: {self.rows_printed()}")
        return " | ".join(parts)

    # --- The one CSV writer ---

    def csv_file_name(self):
        """Like GR-RPT-000123-guard-summary-report.csv."""
        return f"{self.number}-{self._file_label()}.csv"

    def write_csv(self, out):
        """
        The one CSV writer for every report: the title and header rows, then
        each section's title, columns() and rows. It starts with a byte order
        mark, so Excel shows letters like ñ correctly.
        """
        out.write("﻿")
        writer = csv.writer(out)
        writer.writerow([self.title()])
        for label, value in self.header_rows():
            writer.writerow([label, safe_cell(value)])
        for section in self._sections:
            writer.writerow([])
            writer.writerow([section.title])
            writer.writerow(section.columns())
            writer.writerows([safe_cell(cell) for cell in row] for row in section.rows)
