"""
Reports app models: attendance (punctuality) and evaluations (character).

Both are append only. A mistake is fixed by adding a new record, never by
editing an old one. Stage 4 added the rules for recording them: record() is
the only way the app adds one, and it checks the rules first.
"""

from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from audit.models import AppendOnlyRecord
from guards.dates import clock_time, long_date

from .constants import (
    ABSENT,
    EVALUATION_CATEGORIES,
    HIGHEST_SCORE,
    LATE,
    LATE_GRACE_MINUTES,
    LOWEST_SCORE,
    ON_TIME,
)


class AttendanceRecord(AppendOnlyRecord):
    """One duty of one guard on one day."""

    guard = models.ForeignKey(
        "guards.Guard", on_delete=models.PROTECT, related_name="attendance_records"
    )
    date = models.DateField()
    post = models.ForeignKey(
        "deployment.Post", on_delete=models.PROTECT, related_name="attendance_records"
    )
    scheduled_start = models.TimeField()
    time_in = models.TimeField(null=True, blank=True)
    absent = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance_recorded"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["guard", "date"], name="one_duty_per_guard_per_day"),
        ]
        permissions = [
            ("record_performance", "Can add attendance and evaluations"),
            ("view_summary_report", "Can view and download the summary report"),
        ]

    def __str__(self):
        return f"{self.guard} on {self.date}: {self.status()}"

    @staticmethod
    def check_values(time_in, absent):
        """A guard is either absent or has a time in, never both."""
        if absent and time_in:
            raise ValidationError("An absent guard cannot have a time in.")
        if not absent and not time_in:
            raise ValidationError("Enter the time in, or mark the guard as absent.")

    @classmethod
    def for_guard(cls, guard, start, end):
        """His duties from start to end, oldest first, with each post loaded."""
        return (
            cls.objects.filter(guard=guard, date__gte=start, date__lte=end)
            .select_related("post__site")
            .order_by("date")
        )

    @classmethod
    def check_duty(cls, guard, day, time_in, absent):
        """
        The rules for recording one duty. Raises ValidationError with every
        problem found, or returns the posting he worked that day.
        """
        errors = []
        if day > timezone.localdate():
            errors.append("The date cannot be in the future.")
        posting = guard.posting_on(day)
        if posting is None:
            errors.append(f"{guard.full_name} was not posted on {long_date(day)}.")
        if cls.objects.filter(guard=guard, date=day).exists():
            errors.append(
                f"Attendance on {long_date(day)} is already recorded. A record cannot be changed."
            )
        try:
            cls.check_values(time_in, absent)
        except ValidationError as error:
            errors.extend(error.messages)
        if errors:
            raise ValidationError(errors)
        return posting

    @classmethod
    def record(cls, guard, day, time_in, absent, by_user):
        """
        FACTORY: the only way the app records a duty. It checks the rules, then
        takes the post and the shift start from the posting he worked that day.
        """
        post = cls.check_duty(guard, day, time_in, absent).post
        return cls.objects.create(
            guard=guard,
            date=day,
            post=post,
            scheduled_start=post.scheduled_start(),
            time_in=None if absent else time_in,
            absent=absent,
            recorded_by=by_user,
        )

    def minutes_late(self):
        """Minutes after the scheduled start. 0 if early, on time, or absent."""
        if self.absent or self.time_in is None:
            return 0
        start = datetime.combine(self.date, self.scheduled_start)
        arrived = datetime.combine(self.date, self.time_in)
        minutes = int((arrived - start).total_seconds() // 60)
        return max(minutes, 0)

    def is_late(self):
        return not self.absent and self.minutes_late() > LATE_GRACE_MINUTES

    def status(self):
        if self.absent:
            return ABSENT
        if self.is_late():
            return LATE
        return ON_TIME

    def time_in_text(self):
        """Like 5:58 AM, or blank for an absent guard."""
        return clock_time(self.time_in, seconds=False) if self.time_in else ""

    def result_text(self):
        """Like "On time (time in 5:58 AM)", "Late by 12 minutes (time in 6:17 AM)" or "Absent"."""
        if self.absent:
            return ABSENT
        if self.is_late():
            return f"{LATE} by {self.minutes_late()} minutes (time in {self.time_in_text()})"
        return f"{ON_TIME} (time in {self.time_in_text()})"


# Every score must be from 1 to 5.
SCORE_RULES = [MinValueValidator(LOWEST_SCORE), MaxValueValidator(HIGHEST_SCORE)]


class Evaluation(AppendOnlyRecord):
    """A character evaluation. A correction is a new evaluation, never an edit."""

    guard = models.ForeignKey("guards.Guard", on_delete=models.PROTECT, related_name="evaluations")
    date = models.DateField()
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="evaluations_given"
    )
    # One field per category in EVALUATION_CATEGORIES.
    discipline = models.PositiveSmallIntegerField(validators=SCORE_RULES)
    attitude = models.PositiveSmallIntegerField(validators=SCORE_RULES)
    appearance = models.PositiveSmallIntegerField(validators=SCORE_RULES)
    honesty = models.PositiveSmallIntegerField(validators=SCORE_RULES)
    alertness = models.PositiveSmallIntegerField(validators=SCORE_RULES)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.guard} on {self.date}: {self.average()}"

    def scores(self):
        """Category name to score, for example {"Discipline": 4, ...}."""
        return {category: getattr(self, category.lower()) for category in EVALUATION_CATEGORIES}

    def average(self):
        values = list(self.scores().values())
        return round(sum(values) / len(values), 2)

    @classmethod
    def for_guard(cls, guard, start, end):
        """His evaluations from start to end, oldest first, with each evaluator loaded."""
        return (
            cls.objects.filter(guard=guard, date__gte=start, date__lte=end)
            .select_related("evaluator")
            .order_by("date", "id")
        )

    @staticmethod
    def check_values(guard, day, scores):
        """The rules for a new evaluation. Raises ValidationError with every problem found."""
        errors = []
        if day > timezone.localdate():
            errors.append("The date cannot be in the future.")
        if day < guard.date_hired:
            errors.append(
                f"The date cannot be before the hire date ({long_date(guard.date_hired)})."
            )
        for category in EVALUATION_CATEGORIES:
            score = scores.get(category)
            if score is None or not LOWEST_SCORE <= score <= HIGHEST_SCORE:
                errors.append(f"{category} must be a score from {LOWEST_SCORE} to {HIGHEST_SCORE}.")
        if errors:
            raise ValidationError(errors)

    @classmethod
    def record(cls, guard, day, scores, remarks, by_user):
        """FACTORY: the only way the app adds an evaluation. It checks the rules first."""
        cls.check_values(guard, day, scores)
        fields = {category.lower(): scores[category] for category in EVALUATION_CATEGORIES}
        return cls.objects.create(
            guard=guard, date=day, evaluator=by_user, remarks=remarks.strip(), **fields
        )

    @staticmethod
    def category_averages(evaluations):
        """The average score of each category over many evaluations. Empty if there are none."""
        evaluations = list(evaluations)
        if not evaluations:
            return {}
        return {
            category: round(sum(e.scores()[category] for e in evaluations) / len(evaluations), 2)
            for category in EVALUATION_CATEGORIES
        }

    @staticmethod
    def overall_average(evaluations):
        """The average of every score over many evaluations, or None if there are none."""
        evaluations = list(evaluations)
        if not evaluations:
            return None
        return round(sum(e.average() for e in evaluations) / len(evaluations), 2)
