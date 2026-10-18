"""
Forms for the reports app. Admin/HR only.

Compliance reports: there is no JavaScript, so a government request and a
client request are two separate forms. Both extend ComplianceRequestForm.

Guard reports (Stage 4): ReportPeriodForm picks the period, and
SummaryFilterForm adds the two filters of the summary. AttendanceForm and
EvaluationForm extend PerformanceForm, which leaves every rule to the model
(AttendanceRecord.check_duty() and Evaluation.check_values()).
"""

from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from deployment.models import ClientSite
from guards import constants as gc

from .constants import (
    DEFAULT_PERIOD_DAYS,
    EVALUATION_CATEGORIES,
    HIGHEST_SCORE,
    LOWEST_SCORE,
    REMARKS_MAX_LENGTH,
)
from .models import AttendanceRecord, Evaluation

# Bootstrap class for each widget. Any other widget gets "form-control".
WIDGET_CLASSES = {
    forms.CheckboxSelectMultiple: "form-check-input",
    forms.CheckboxInput: "form-check-input",
    forms.Select: "form-select",
}


def date_input():
    """A browser date picker. No JavaScript needed."""
    return forms.DateInput(attrs={"type": "date"})


def style(form_fields, size=""):
    """Give every field its Bootstrap class, like form-control or form-select."""
    for field in form_fields.values():
        css = WIDGET_CLASSES.get(type(field.widget), "form-control")
        field.widget.attrs["class"] = f"{css} {css}-{size}".strip() if size else css


class ComplianceRequestForm(forms.Form):
    """The details of a written request, the sections to print, and a password re-check."""

    # The request details every report prints in its header, in this order.
    REQUEST_FIELDS = [
        "requesting_party",
        "contact_name",
        "contact_position",
        "reference_number",
        "purpose",
        "period_start",
        "period_end",
    ]

    requesting_party = forms.CharField(label="Requesting party (office or company)", max_length=150)
    contact_name = forms.CharField(label="Name of the person asking", max_length=100)
    contact_position = forms.CharField(label="Position of the person asking", max_length=100)
    reference_number = forms.CharField(
        label="Reference number of their written request", max_length=60
    )
    purpose = forms.CharField(
        label="Purpose stated in the request",
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    # No default dates on purpose: type the period from the written request,
    # so the report never covers more than the requester asked for.
    period_start = forms.DateField(
        label="Period covered: from",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Type the period from the written request.",
    )
    period_end = forms.DateField(
        label="Period covered: to",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    sections = forms.MultipleChoiceField(
        label="Sections to print",
        widget=forms.CheckboxSelectMultiple,
        help_text="Untick any section the request does not need.",
        error_messages={"required": "Tick at least one section."},
    )
    password = forms.CharField(
        label="Re-enter your password",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        help_text="A wrong password is refused and recorded in the audit log.",
    )

    def __init__(self, user, section_choices, default_sections, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Only this report's own sections are offered. Django rejects any
        # other value as "not one of the available choices".
        self.fields["sections"].choices = section_choices
        self.fields["sections"].initial = default_sections
        for field in self.fields.values():
            field.widget.attrs["class"] = WIDGET_CLASSES.get(type(field.widget), "form-control")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start")
        end = cleaned.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "The end date cannot be before the start date.")
        if end and end > timezone.localdate():
            self.add_error("period_end", "The period cannot end in the future.")
        return cleaned

    def password_ok(self):
        """True only if the password matches. The view refuses the request with deny() if not."""
        return self.user.check_password(self.cleaned_data["password"])

    def request_details(self):
        """The request details the report prints in its header."""
        return {name: self.cleaned_data[name] for name in self.REQUEST_FIELDS}


class GovernmentRequestForm(ComplianceRequestForm):
    """A request from a government office. Adds the legal basis the office cited."""

    legal_basis = forms.CharField(
        label="Legal basis or authority stated in their request",
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    field_order = [
        "requesting_party",
        "contact_name",
        "contact_position",
        "reference_number",
        "legal_basis",
        "purpose",
        "period_start",
        "period_end",
        "sections",
        "password",
    ]

    def request_details(self):
        """POLYMORPHISM: the shared details plus the legal basis."""
        details = super().request_details()
        details["legal_basis"] = self.cleaned_data["legal_basis"]
        return details


class ClientRequestForm(ComplianceRequestForm):
    """A request from a client. Adds the one site the report covers."""

    site = forms.ModelChoiceField(
        label="Client site",
        queryset=ClientSite.objects.all(),
        empty_label="Choose the client site",
        help_text="The report covers this site only.",
    )

    field_order = [
        "site",
        "requesting_party",
        "contact_name",
        "contact_position",
        "reference_number",
        "purpose",
        "period_start",
        "period_end",
        "sections",
        "password",
    ]

    def request_details(self):
        """POLYMORPHISM: the shared details plus the client site."""
        details = super().request_details()
        details["site"] = self.cleaned_data["site"]
        return details


# ---------------------------------------------------------------------------
# Guard reports (Stage 4)
# ---------------------------------------------------------------------------


def default_period():
    """The last DEFAULT_PERIOD_DAYS days, ending today."""
    today = timezone.localdate()
    return today - timedelta(days=DEFAULT_PERIOD_DAYS - 1), today


class ReportPeriodForm(forms.Form):
    """The period a guard report covers. Empty dates mean the last 90 days, ending today."""

    start = forms.DateField(label="From", required=False, widget=date_input())
    end = forms.DateField(label="To", required=False, widget=date_input())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        start, end = default_period()
        self.fields["start"].initial = start
        self.fields["end"].initial = end
        style(self.fields, size="sm")

    def clean(self):
        cleaned = super().clean()
        default_start, default_end = default_period()
        start = cleaned.get("start") or default_start
        end = cleaned.get("end") or default_end
        if end > timezone.localdate():
            self.add_error("end", "The period cannot end in the future.")
        if start > end:
            self.add_error("start", "The start date cannot be after the end date.")
        cleaned["start"], cleaned["end"] = start, end
        return cleaned

    def filters(self):
        """The chosen values, or the defaults when the form is empty or has an error."""
        if self.is_bound and self.is_valid():
            return {name: self.cleaned_data[name] for name in self.fields}
        return self.defaults()

    def defaults(self):
        start, end = default_period()
        return {"start": start, "end": end}

    def problems(self):
        """Every error message in one line, for the audit log."""
        return " ".join(error for errors in self.errors.values() for error in errors)


class SummaryFilterForm(ReportPeriodForm):
    """The period, plus which guards (current or who left) and one guard type or all."""

    show = forms.ChoiceField(
        label="Which guards", required=False, choices=list(gc.EMPLOYMENT_FILTERS.items())
    )
    guard_type = forms.ChoiceField(
        label="Guard type",
        required=False,
        choices=[("", "Any guard type")] + gc.GUARD_TYPE_CHOICES,
    )

    def filters(self):
        """POLYMORPHISM: the period filters, and current guards when Which guards is empty."""
        filters = super().filters()
        filters["show"] = filters.get("show") or gc.SHOW_CURRENT
        filters.setdefault("guard_type", "")
        return filters


class PerformanceForm(forms.Form):
    """
    The base of the attendance and evaluation forms. It is never used on its
    own. The form only reads the values; the model's own rules decide.
    """

    TITLE = ""

    def __init__(self, guard, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guard = guard
        style(self.fields)

    @property
    def title(self):
        return self.TITLE

    def clean(self):
        """Once every field is fine, ask the model's rules. Each problem shows at the top."""
        cleaned = super().clean()
        if not self.errors:
            try:
                self._check(cleaned)
            except ValidationError as error:
                for message in error.messages:
                    self.add_error(None, message)
        return cleaned

    def _check(self, cleaned):
        """Ask the model's rules, which raise ValidationError. Each form overrides this."""
        raise NotImplementedError("Each form asks its own model's rules.")

    def problems(self):
        """Every error message in one line, for the audit log. Messages never repeat a value."""
        messages = [error for errors in self.errors.values() for error in errors]
        if not messages:
            return ""
        return f"{self.title}: {' '.join(messages)}"


class AttendanceForm(PerformanceForm):
    """One duty of one guard: the date, and his time in or absent."""

    TITLE = "Record attendance"

    date = forms.DateField(label="Date of duty", initial=timezone.localdate, widget=date_input())
    time_in = forms.TimeField(
        label="Time in",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
        help_text="Leave it empty if the guard was absent.",
    )
    absent = forms.BooleanField(label="Absent", required=False)

    def _check(self, cleaned):
        """POLYMORPHISM: AttendanceRecord.check_duty() decides."""
        AttendanceRecord.check_duty(self._guard, **self.values())

    def values(self):
        """The values AttendanceRecord.record() takes."""
        return {
            "day": self.cleaned_data["date"],
            "time_in": self.cleaned_data.get("time_in"),
            "absent": self.cleaned_data.get("absent", False),
        }


class EvaluationForm(PerformanceForm):
    """A character evaluation: the date, a score for each category, and remarks."""

    TITLE = "Add evaluation"

    date = forms.DateField(
        label="Date of evaluation", initial=timezone.localdate, widget=date_input()
    )
    remarks = forms.CharField(
        label="Remarks",
        required=False,
        max_length=REMARKS_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional. Facts about the work only.",
    )

    def __init__(self, guard, *args, **kwargs):
        super().__init__(guard, *args, **kwargs)
        # One score field per category in EVALUATION_CATEGORIES, named like the model field.
        scores = [("", "Choose")] + [
            (score, str(score)) for score in range(LOWEST_SCORE, HIGHEST_SCORE + 1)
        ]
        for category in EVALUATION_CATEGORIES:
            self.fields[category.lower()] = forms.TypedChoiceField(
                label=f"{category} ({LOWEST_SCORE} to {HIGHEST_SCORE})",
                choices=scores,
                coerce=int,
                error_messages={"required": f"Choose a score for {category.lower()}."},
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        self.order_fields(["date"] + [category.lower() for category in EVALUATION_CATEGORIES])

    def _check(self, cleaned):
        """POLYMORPHISM: Evaluation.check_values() decides."""
        values = self.values()
        Evaluation.check_values(self._guard, values["day"], values["scores"])

    def values(self):
        """The values Evaluation.record() takes."""
        return {
            "day": self.cleaned_data["date"],
            "scores": {
                category: self.cleaned_data[category.lower()] for category in EVALUATION_CATEGORIES
            },
            "remarks": self.cleaned_data.get("remarks", ""),
        }
