"""Forms for login and the step-up check."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Django's own login form, with Bootstrap styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class StepUpForm(forms.Form):
    """Re-enter the password and give a reason before seeing sensitive data."""

    password = forms.CharField(
        label="Your password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "current-password"}),
    )
    reason = forms.CharField(
        label="Reason for opening these records",
        max_length=200,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        # check_password() compares against Django's salted hash.
        if not self.user.check_password(password):
            raise forms.ValidationError("Wrong password.")
        return password

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if len(reason) < 5:
            raise forms.ValidationError("Give a short reason (at least 5 characters).")
        return reason

    def problems(self):
        """All error messages in one line, for the audit log."""
        return " ".join(error for errors in self.errors.values() for error in errors)
