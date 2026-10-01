"""
Reports app models: attendance (punctuality) and evaluations (character).

Both are append only. A mistake is fixed by adding a new record, never by
editing an old one.
"""

from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from audit.models import AppendOnlyRecord

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
