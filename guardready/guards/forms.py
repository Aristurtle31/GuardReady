"""Forms for the guards app."""

from django import forms
from django.utils import timezone

from .models import Guard


class GuardForm(forms.ModelForm):
    """
    Add a new guard. Admin/HR only.

    The sensitive fields are on this form on purpose. Typing them in is a
    different act from browsing them, so the view logs the whole thing as a
    sensitive CREATE entry. Reading them back on the profile still needs a
    step-up, exactly as before.

    The login account is not on this form. Linking a guard to a user is not
    part of this feature.
    """

    class Meta:
        model = Guard
        fields = [
            "employee_no",
            "first_name",
            "last_name",
            "date_hired",
            "rank",
            "position",
            "guard_type",
            "birth_date",
            "contact_number",
            "home_address",
            "sss_number",
            "tin_number",
            "philhealth_number",
        ]
        widgets = {
            "date_hired": forms.DateInput(attrs={"type": "date"}),
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "home_address": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "employee_no": "Employee number",
            "date_hired": "Date hired",
            "guard_type": "Guard type",
            "birth_date": "Date of birth",
            "contact_number": "Contact number",
            "home_address": "Home address",
            "sss_number": "SSS number",
            "tin_number": "TIN",
            "philhealth_number": "PhilHealth number",
        }
        help_texts = {
            "employee_no": "Must be different from every other guard, for example GR-0009.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bootstrap styling, the same way LoginForm does it.
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean_employee_no(self):
        """Trim stray spaces so two records cannot differ by a space alone."""
        return self.cleaned_data["employee_no"].strip()

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def clean_date_hired(self):
        date_hired = self.cleaned_data["date_hired"]
        if date_hired > timezone.localdate():
            raise forms.ValidationError("The date hired cannot be in the future.")
        return date_hired

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get("birth_date")
        if birth_date and birth_date >= timezone.localdate():
            raise forms.ValidationError("The date of birth must be in the past.")
        return birth_date

    def problems(self):
        """All error messages in one line, for the audit log."""
        return " ".join(error for errors in self.errors.values() for error in errors)
