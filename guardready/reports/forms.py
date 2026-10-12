"""
Request forms for compliance reports. Admin/HR only.

There is no JavaScript, so a government request and a client request are
two separate forms. Both extend ComplianceRequestForm.
"""

from django import forms
from django.utils import timezone

from deployment.models import ClientSite

# Bootstrap class for each widget. Any other widget gets "form-control".
WIDGET_CLASSES = {
    forms.CheckboxSelectMultiple: "form-check-input",
    forms.Select: "form-select",
}


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
