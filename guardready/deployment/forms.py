"""
The assign form. Admin/HR only.

The form only checks that a real guard was picked. Whether he can be posted
is decided by Post.refusal_reasons(), which assign_guard() asks on submit.
"""

from django import forms

from guards.models import Guard


class AssignGuardForm(forms.Form):
    """The guard to post. The page lists the guards as a table of radio buttons."""

    guard = forms.ModelChoiceField(
        queryset=Guard.objects.all(),
        error_messages={
            "required": "Pick a guard first.",
            "invalid_choice": "Pick a guard from the list.",
        },
    )

    def problems(self):
        """Every error message in one line, for the audit log."""
        return " ".join(error for errors in self.errors.values() for error in errors)
