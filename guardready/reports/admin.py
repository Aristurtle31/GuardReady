"""Read-only admin screens for the superuser."""

from django.contrib import admin

from audit.admin import ReadOnlyAdmin

from .models import AttendanceRecord, Evaluation


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ReadOnlyAdmin):
    list_display = ["guard", "date", "post", "scheduled_start", "time_in", "absent"]
    list_filter = ["absent"]


@admin.register(Evaluation)
class EvaluationAdmin(ReadOnlyAdmin):
    list_display = ["guard", "date", "evaluator", "discipline", "attitude", "appearance", "honesty", "alertness"]
