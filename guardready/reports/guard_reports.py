"""
Guard reports (scope item 3): punctuality, guard type and character evaluation.

GuardReport covers one guard. SummaryReport covers many guards, one row each.
Both are for Admin/HR. On screen they are plain pages; the Download CSV button
writes one REPORT audit entry and gives the file that report number.

OOP in this file
- INHERITANCE: GuardReport and SummaryReport extend Report (reports/base.py),
  the same base class as the compliance reports. Their tables extend
  ReportSection.
- POLYMORPHISM: each report overrides title(), sections() and
  _request_rows(). Each table overrides columns() and _collect(). The one CSV
  writer, Report.write_csv(), calls them, so neither report has CSV code.
- ENCAPSULATION: Punctuality keeps its counts in _counts, with read-only
  properties. A report keeps its guard and filters in protected attributes.

Never in these reports: medical results, birth date, home address, contact
number, SSS, TIN and PhilHealth numbers.
"""

from guards import constants as gc
from guards.dates import clock_time, long_date
from guards.services import all_guards, filter_by_employment

from .base import Report, ReportSection, person_name
from .constants import (
    ABSENT,
    ATTENDANCE_STATUSES,
    EVALUATION_CATEGORIES,
    HIGHEST_SCORE,
    LATE,
    LATE_GRACE_MINUTES,
    LOWEST_SCORE,
    NO_DUTIES,
    NO_EVALUATIONS,
    ON_TIME,
)
from .models import AttendanceRecord, Evaluation


def score_text(score):
    """A score like 4.40, or None when there is nothing to average."""
    return NO_EVALUATIONS if score is None else f"{score:.2f}"


class Punctuality:
    """ENCAPSULATION: how many duties were on time, late or absent, with read-only counts."""

    def __init__(self, records):
        self._counts = {status: 0 for status in ATTENDANCE_STATUSES}
        for record in records:
            self._counts[record.status()] += 1

    def __str__(self):
        return f"{self.duties} duties, {self.rate_text()} on time"

    @property
    def duties(self):
        return sum(self._counts.values())

    @property
    def on_time(self):
        return self._counts[ON_TIME]

    @property
    def late(self):
        return self._counts[LATE]

    @property
    def absent(self):
        return self._counts[ABSENT]

    def rate(self):
        """Duties on time, out of 100. An absence counts as not on time. None with no duties."""
        if self.duties == 0:
            return None
        return round(self.on_time * 100 / self.duties)

    def rate_text(self):
        """Like 92%, or No duties."""
        rate = self.rate()
        return NO_DUTIES if rate is None else f"{rate}%"


# ---------------------------------------------------------------------------
# Tables of a GuardReport (one guard)
# ---------------------------------------------------------------------------


class PeriodSummarySection(ReportSection):
    """The guard's totals for the period: punctuality, then the evaluation averages."""

    KEY = "summary"
    TITLE = "Summary for the period"
    NOTE = (
        f"On time means timing in no more than {LATE_GRACE_MINUTES} minutes after the "
        "shift started. An absence counts as not on time."
    )

    def columns(self):
        return ["What was counted", "Value"]

    def _collect(self):
        report = self._report
        guard = report.guard
        punctuality = Punctuality(report.attendance())
        evaluations = list(report.evaluations())
        averages = Evaluation.category_averages(evaluations)
        rows = [
            self._guard_row(guard, "Duties", punctuality.duties),
            self._guard_row(guard, "On time", punctuality.on_time),
            self._guard_row(guard, "Late", punctuality.late),
            self._guard_row(guard, "Absent", punctuality.absent),
            self._guard_row(guard, "Punctuality", punctuality.rate_text()),
            self._guard_row(guard, "Evaluations", len(evaluations)),
            self._guard_row(
                guard, "Average score", score_text(Evaluation.overall_average(evaluations))
            ),
        ]
        rows += [
            self._guard_row(guard, f"Average {category.lower()}", score_text(averages.get(category)))
            for category in EVALUATION_CATEGORIES
        ]
        return rows


class AttendanceSection(ReportSection):
    """Every duty of the guard in the period, oldest first."""

    KEY = "attendance"
    TITLE = "Attendance in the period"

    def columns(self):
        return ["Date", "Post", "Shift starts", "Time in", "Status", "Minutes late"]

    def _collect(self):
        guard = self._report.guard
        return [
            self._guard_row(
                guard,
                long_date(record.date),
                str(record.post),
                clock_time(record.scheduled_start, seconds=False),
                record.time_in_text(),
                record.status(),
                record.minutes_late(),
            )
            for record in self._report.attendance()
        ]


class EvaluationSection(ReportSection):
    """Every character evaluation of the guard in the period, oldest first."""

    KEY = "evaluations"
    TITLE = "Character evaluations in the period"
    NOTE = f"Each category is scored from {LOWEST_SCORE} (lowest) to {HIGHEST_SCORE} (highest)."

    def columns(self):
        return ["Date", "Evaluator"] + EVALUATION_CATEGORIES + ["Average", "Remarks"]

    def _collect(self):
        guard = self._report.guard
        rows = []
        for evaluation in self._report.evaluations():
            scores = [evaluation.scores()[category] for category in EVALUATION_CATEGORIES]
            rows.append(
                self._guard_row(
                    guard,
                    long_date(evaluation.date),
                    person_name(evaluation.evaluator),
                    *scores,
                    score_text(evaluation.average()),
                    evaluation.remarks,
                )
            )
        return rows


# ---------------------------------------------------------------------------
# The table of a SummaryReport (many guards)
# ---------------------------------------------------------------------------


class GuardListSection(ReportSection):
    """One row per guard: his guard type, punctuality and average evaluation score."""

    KEY = "guards"
    TITLE = "Guards"
    NOTE = "Punctuality is the share of duties on time. An absence counts as not on time."

    def __init__(self, report):
        super().__init__(report)
        # The guard behind each row, in row order, so the page can link to his report.
        self._listed = []

    def columns(self):
        return [
            "Name",
            "Employee no.",
            "Guard type",
            "Duties",
            "On time",
            "Late",
            "Absent",
            "Punctuality",
            "Evaluations",
            "Average score",
        ]

    def _collect(self):
        report = self._report
        rows = []
        for guard in report.guards():
            punctuality = Punctuality(report.attendance(guard))
            evaluations = list(report.evaluations(guard))
            self._listed.append(guard)
            rows.append(
                self._guard_row(
                    guard,
                    guard.full_name,
                    guard.employee_no,
                    guard.guard_type,
                    punctuality.duties,
                    punctuality.on_time,
                    punctuality.late,
                    punctuality.absent,
                    punctuality.rate_text(),
                    len(evaluations),
                    score_text(Evaluation.overall_average(evaluations)),
                )
            )
        return rows

    @property
    def listed_guards(self):
        return list(self._listed)


# ---------------------------------------------------------------------------
# The two guard reports
# ---------------------------------------------------------------------------


class GuardReport(Report):
    """One guard's punctuality and character evaluations for a period, with his guard type."""

    TARGET_TYPE = "GuardReport"
    OUTPUT = "exported"

    def __init__(self, guard, period_start, period_end, prepared_by):
        super().__init__(period_start, period_end, prepared_by)
        self._guard = guard

    @classmethod
    def from_filters(cls, guard, filters, prepared_by):
        """FACTORY: the report for one guard and the period from the form."""
        return cls(guard, filters["start"], filters["end"], prepared_by)

    @property
    def guard(self):
        return self._guard

    @classmethod
    def title(cls):
        return "Guard Report"

    @classmethod
    def sections(cls):
        return [PeriodSummarySection, AttendanceSection, EvaluationSection]

    def _request_rows(self):
        """POLYMORPHISM: the guard (with his guard type) and the period."""
        return [
            ("Guard", self._guard.summary()),
            ("Rank", self._guard.rank),
            ("Employment status", self._guard.employment_status().name),
            ("Period covered", self.period_text()),
        ]

    def _file_label(self):
        """POLYMORPHISM: the shared name plus his employee number."""
        return f"{super()._file_label()}-{self._guard.employee_no.lower()}"

    def attendance(self):
        return AttendanceRecord.for_guard(self._guard, self.period_start, self.period_end)

    def evaluations(self):
        return Evaluation.for_guard(self._guard, self.period_start, self.period_end)


class SummaryReport(Report):
    """Punctuality and average score of many guards, one row each, with their guard type."""

    TARGET_TYPE = "SummaryReport"
    OUTPUT = "exported"

    def __init__(self, period_start, period_end, prepared_by, show=gc.SHOW_CURRENT, guard_type=""):
        super().__init__(period_start, period_end, prepared_by)
        self._show = show
        self._guard_type = guard_type

    @classmethod
    def from_filters(cls, filters, prepared_by):
        """FACTORY: the report for the period and the two filters from the form."""
        return cls(
            filters["start"], filters["end"], prepared_by, filters["show"], filters["guard_type"]
        )

    @classmethod
    def title(cls):
        return "Guard Summary Report"

    @classmethod
    def sections(cls):
        return [GuardListSection]

    def _request_rows(self):
        """POLYMORPHISM: the period and the two filters."""
        which = gc.EMPLOYMENT_FILTERS.get(self._show, gc.EMPLOYMENT_FILTERS[gc.SHOW_CURRENT])
        return [
            ("Period covered", self.period_text()),
            ("Which guards", which),
            ("Guard type", self._guard_type or "Any"),
        ]

    def guards(self):
        """
        Current guards by default, or the guards who left. Each status object
        decides (filter_by_employment). Then only one guard type, if one was picked.
        """
        guards = filter_by_employment(all_guards(), self._show)
        if self._guard_type:
            guards = [guard for guard in guards if guard.guard_type == self._guard_type]
        return guards

    def attendance(self, guard):
        return AttendanceRecord.for_guard(guard, self.period_start, self.period_end)

    def evaluations(self, guard):
        return Evaluation.for_guard(guard, self.period_start, self.period_end)

    def lines(self):
        """(guard, cells) for each row of the built table, so the page can link each name."""
        if not self._sections:
            return []
        section = self._sections[0]
        return list(zip(section.listed_guards, section.rows))
