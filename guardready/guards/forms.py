"""
Forms for the guards app: one ModelForm class for each section of a guard's
record. The forms only check values. Saving happens in guards/services.py,
through the model methods add_credential() and renew().

OOP in this file
- INHERITANCE: SectionForm is the base of every section form.
  ExpiringDocumentForm holds the date checks shared by guard documents and
  agency permits, like ExpiringDocument does for the models.
  CredentialForm -> MedicalCredentialForm adds the result field, the same way
  MedicalCert overrides uses_result(). CredentialForm -> RenewCredentialForm
  -> MedicalRenewCredentialForm does the same for a renewal.
  PermitForm -> RenewPermitForm do the same for an agency permit.
- POLYMORPHISM: each form has its own fields, title, sensitive fields and
  old_values(). The shared steps (styling, audit text) stay in SectionForm.
- COMPOSITION: AddGuardForms owns every section form of the Add Guard page.
- FACTORY: add_form_class() and renew_form_class() pick the form class with a
  dict, by asking the credential uses_result(). No if/elif on its kind.
- StatusChangeForm offers only the next statuses the guard's current status
  allows, and leaves every rule to Guard.check_status_change().
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from audit.changes import ChangeSummary

from . import constants as c
from .models import AgencyPermit, Credential, Guard

# Contact number, SSS, TIN and PhilHealth (see guards/constants.py).
number_text = RegexValidator(c.NUMBER_TEXT_PATTERN, c.NUMBER_TEXT_MESSAGE)

# Bootstrap class for each widget. Any other widget gets "form-control".
WIDGET_CLASSES = {forms.Select: "form-select"}


def date_input():
    """A browser date picker. No JavaScript needed."""
    return forms.DateInput(attrs={"type": "date"})


# ---------------------------------------------------------------------------
# The base class of every section
# ---------------------------------------------------------------------------


class SectionForm(forms.ModelForm):
    """One section of a guard's record, with Bootstrap styling and audit text."""

    TITLE = ""
    # Never written to the audit log with their values (RA 10173).
    SENSITIVE_FIELDS = []
    # Accept only digits, spaces, dashes and a leading +.
    NUMBER_TEXT_FIELDS = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = WIDGET_CLASSES.get(type(field.widget), "form-control")
            if name in self.NUMBER_TEXT_FIELDS:
                field.validators.append(number_text)

    def full_clean(self):
        """After the check, give every box with an error a red border (Bootstrap is-invalid)."""
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                self.fields[name].widget.attrs["class"] += " is-invalid"

    @property
    def title(self):
        """The heading of this section on the page."""
        return self.TITLE

    def has_sensitive_fields(self):
        return any(name in self.fields for name in self.SENSITIVE_FIELDS)

    def problems(self):
        """Every error message in one line, for the audit log. Messages never repeat a value."""
        messages = [error for errors in self.errors.values() for error in errors]
        if not messages:
            return ""
        return f"{self.title}: {' '.join(messages)}"

    def old_values(self):
        """The values before this save. A ModelForm keeps them in initial."""
        return self.initial

    def describe_changes(self, summary):
        """Add every field this edit changed to a ChangeSummary."""
        old = self.old_values()
        for name, field in self.fields.items():
            summary.changed(
                field.label, old.get(name), self.cleaned_data.get(name), name in self.SENSITIVE_FIELDS
            )
        return summary

    def describe_new(self, summary):
        """Add every field of a new record to a ChangeSummary."""
        for name, field in self.fields.items():
            summary.filled(field.label, self.cleaned_data.get(name), name in self.SENSITIVE_FIELDS)
        return summary


# ---------------------------------------------------------------------------
# Guard sections
# ---------------------------------------------------------------------------


class GuardBasicForm(SectionForm):
    """Basic details. None of them is sensitive, so editing them needs no step-up."""

    TITLE = "Basic details"

    class Meta:
        model = Guard
        fields = [
            "first_name",
            "last_name",
            "employee_no",
            "date_hired",
            "position",
            "rank",
            "guard_type",
        ]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "employee_no": "Employee no.",
            "date_hired": "Date hired",
            "guard_type": "Guard type",
        }
        help_texts = {
            "employee_no": "Must be different from every other guard, for example GR-0009.",
        }
        widgets = {"date_hired": date_input()}
        error_messages = {
            "employee_no": {"unique": "This employee no. already belongs to another guard."},
        }

    def clean_date_hired(self):
        date_hired = self.cleaned_data["date_hired"]
        if date_hired > timezone.localdate():
            raise forms.ValidationError("The date hired cannot be in the future.")
        return date_hired


class GuardPersonalForm(SectionForm):
    """Date of birth, contact number and home address. Sensitive under RA 10173."""

    TITLE = "Personal details"
    SENSITIVE_FIELDS = c.PERSONAL_FIELDS
    NUMBER_TEXT_FIELDS = ["contact_number"]

    class Meta:
        model = Guard
        fields = c.PERSONAL_FIELDS
        labels = {
            "birth_date": "Date of birth",
            "contact_number": "Contact number",
            "home_address": "Home address",
        }
        widgets = {
            "birth_date": date_input(),
            "home_address": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get("birth_date")
        if birth_date and birth_date >= timezone.localdate():
            raise forms.ValidationError("The date of birth must be in the past.")
        return birth_date


class GuardGovernmentForm(SectionForm):
    """SSS, TIN and PhilHealth numbers. Sensitive under RA 10173."""

    TITLE = "Government numbers"
    SENSITIVE_FIELDS = c.GOVERNMENT_NUMBER_FIELDS
    NUMBER_TEXT_FIELDS = c.GOVERNMENT_NUMBER_FIELDS

    class Meta:
        model = Guard
        fields = c.GOVERNMENT_NUMBER_FIELDS
        labels = {
            "sss_number": "SSS number",
            "tin_number": "TIN",
            "philhealth_number": "PhilHealth number",
        }


# ---------------------------------------------------------------------------
# Documents with dates: guard documents and agency permits
# ---------------------------------------------------------------------------


class ExpiringDocumentForm(SectionForm):
    """The date checks shared by every document form. Never used on its own."""

    def clean(self):
        """The model's own rules: the issue date is not in the future, and expiry comes after it."""
        cleaned = super().clean()
        number, issued, expires = (cleaned.get(name) for name in ("number", "issued", "expires"))
        if number and issued and expires:
            try:
                self._meta.model.check_values(number, issued, expires)
            except ValidationError as error:
                for message in error.messages:
                    self.add_error(None, message)
        return cleaned

    def values(self):
        """The keyword values for the add method or renew()."""
        return {name: self.cleaned_data[name] for name in self.fields}


# ---------------------------------------------------------------------------
# Document (credential) sections
# ---------------------------------------------------------------------------


class CredentialForm(ExpiringDocumentForm):
    """One document: number, issuer and dates. Saved only through Guard.add_credential()."""

    # Never saved with form.save(). guards/services.py passes values() to
    # Guard.add_credential(), the only way to put a document on file.

    class Meta:
        model = Credential
        fields = ["number", "issuer", "issued", "expires"]
        labels = {
            "number": "Document number",
            "issuer": "Issued by",
            "issued": "Date issued",
            "expires": "Expiry date",
            "result": "Result",
        }
        help_texts = {
            "result": "Sensitive. The profile shows it only after a step-up.",
        }
        widgets = {"issued": date_input(), "expires": date_input()}
        error_messages = {
            "number": {"required": "Enter the document number."},
            "issued": {"required": "Enter the date issued."},
            "expires": {"required": "Enter the expiry date."},
        }

    def __init__(self, *args, doc_type, **kwargs):
        super().__init__(*args, **kwargs)
        self._doc_type = doc_type

    @property
    def doc_type(self):
        return self._doc_type

    @property
    def title(self):
        """POLYMORPHISM: a document section is titled with the document name."""
        return self._doc_type


class MedicalCredentialForm(CredentialForm):
    """POLYMORPHISM: a drug test or neuro-psych exam also has a result, and it is sensitive."""

    SENSITIVE_FIELDS = ["result"]

    class Meta(CredentialForm.Meta):
        fields = CredentialForm.Meta.fields + ["result"]


class RenewCredentialForm(CredentialForm):
    """Renew or correct a document on file. Saved only through Credential.renew()."""

    # guards/services.py passes values() to Credential.renew(), which saves
    # the old values in a CredentialVersion first. There is no issuer field:
    # renew() keeps the issuer, because CredentialVersion has no old issuer.
    NOTHING_CHANGED = "Nothing was changed. Change at least one value, or press Cancel."

    class Meta(CredentialForm.Meta):
        fields = ["number", "issued", "expires"]

    def __init__(self, *args, credential, **kwargs):
        # ENCAPSULATION: the stored values are copied before anything can change them.
        self._old = {name: getattr(credential, name) for name in self._meta.fields}
        # Pre-filled as a renewal from today. Change the dates if the paper says otherwise.
        today = timezone.localdate()
        initial = dict(self._old, issued=today, expires=credential.suggested_expiry(today))
        super().__init__(*args, doc_type=credential.doc_type, initial=initial, **kwargs)

    def old_values(self):
        """POLYMORPHISM: compare with the stored document, not with the pre-filled dates."""
        return dict(self._old)

    def clean(self):
        """A renewal that changes nothing would only add an empty history row."""
        cleaned = super().clean()
        if not self.errors and not self.describe_changes(ChangeSummary()):
            raise forms.ValidationError(self.NOTHING_CHANGED)
        return cleaned


class MedicalRenewCredentialForm(RenewCredentialForm):
    """POLYMORPHISM: renewing a medical exam can also change its sensitive result."""

    SENSITIVE_FIELDS = ["result"]

    class Meta(RenewCredentialForm.Meta):
        fields = RenewCredentialForm.Meta.fields + ["result"]


# FACTORY: the key answers "does this form show the result field?"
CREDENTIAL_FORMS = {False: CredentialForm, True: MedicalCredentialForm}
RENEW_FORMS = {False: RenewCredentialForm, True: MedicalRenewCredentialForm}


def add_form_class(credential, show_result):
    """
    Like create_account() in the bank activity: ask the typed credential
    uses_result(), then pick the class from a dict. The result shows only
    when show_result is True (a new guard, or an active step-up).
    """
    return CREDENTIAL_FORMS[credential.uses_result() and show_result]


def renew_form_class(credential, show_result):
    """The same choice for a renewal."""
    return RENEW_FORMS[credential.uses_result() and show_result]


# ---------------------------------------------------------------------------
# Agency permits (like the License to Operate)
# ---------------------------------------------------------------------------


class PermitForm(ExpiringDocumentForm):
    """One agency permit: number, issuer and dates. Saved only through AgencyPermit.add()."""

    class Meta:
        model = AgencyPermit
        fields = ["number", "issuer", "issued", "expires"]
        labels = {
            "number": "Permit number",
            "issuer": "Issued by",
            "issued": "Date issued",
            "expires": "Expiry date",
        }
        help_texts = {
            "expires": "Type the expiry date printed on the permit. GuardReady never fills it in.",
        }
        widgets = {"issued": date_input(), "expires": date_input()}
        error_messages = {
            "number": {"required": "Enter the permit number."},
            "issued": {"required": "Enter the date issued."},
            "expires": {"required": "Enter the expiry date printed on the permit."},
        }

    def __init__(self, *args, permit, **kwargs):
        super().__init__(*args, **kwargs)
        self._permit = permit

    @property
    def title(self):
        """POLYMORPHISM: a permit section is titled with the permit name."""
        return self._permit.name()


class RenewPermitForm(PermitForm):
    """Renew or correct an agency permit on file. Saved only through renew()."""

    # There is no issuer field: renew() keeps the issuer, because
    # AgencyPermitVersion has no old issuer (the same as guard documents).
    NOTHING_CHANGED = RenewCredentialForm.NOTHING_CHANGED

    class Meta(PermitForm.Meta):
        fields = ["number", "issued", "expires"]

    def __init__(self, *args, permit, **kwargs):
        # ENCAPSULATION: the stored values are copied before anything can change them.
        self._old = {name: getattr(permit, name) for name in self._meta.fields}
        # The number and the issue date start as they are on file, so a typo is
        # easy to fix. The expiry date starts empty on purpose: HR types the
        # date printed on the permit.
        initial = {"number": permit.number, "issued": permit.issued}
        super().__init__(*args, permit=permit, initial=initial, **kwargs)

    def old_values(self):
        """POLYMORPHISM: compare with the permit on file."""
        return dict(self._old)

    def clean(self):
        """A save that changes nothing would only add an empty history row."""
        cleaned = super().clean()
        if not self.errors and not self.describe_changes(ChangeSummary()):
            raise forms.ValidationError(self.NOTHING_CHANGED)
        return cleaned


# ---------------------------------------------------------------------------
# The Add Guard page: every section together
# ---------------------------------------------------------------------------


class AddGuardForms:
    """COMPOSITION: the Add Guard page owns one form per section and checks them together."""

    def __init__(self, data=None):
        # The three detail sections fill in one new, unsaved Guard.
        self._guard = Guard()
        self._details = [
            GuardBasicForm(data, instance=self._guard, prefix="basic"),
            GuardPersonalForm(data, instance=self._guard, prefix="personal"),
            GuardGovernmentForm(data, instance=self._guard, prefix="government"),
        ]
        # One section per required document. empty_permitted lets a section
        # stay empty: the guard then shows "Not on file" and is Not cleared,
        # which is correct. If any box is filled, the section is checked in full.
        self._documents = [
            add_form_class(Credential.for_document(doc_type), show_result=True)(
                data,
                doc_type=doc_type,
                prefix=slug,
                empty_permitted=True,
                use_required_attribute=False,
            )
            for slug, doc_type in c.DOCUMENT_SLUGS.items()
        ]

    def __str__(self):
        return f"Add Guard page with {len(self._all())} sections"

    def _all(self):
        return self._details + self._documents

    # --- For the template ---

    @property
    def basic(self):
        return self._details[0]

    @property
    def personal(self):
        return self._details[1]

    @property
    def government(self):
        return self._details[2]

    @property
    def documents(self):
        return list(self._documents)

    # --- For the view and guards/services.py ---

    def is_valid(self):
        """Every section is checked, so the page shows all errors at once."""
        results = [form.is_valid() for form in self._all()]
        return all(results)

    def has_sensitive_fields(self):
        return any(form.has_sensitive_fields() for form in self._all())

    def problems(self):
        """Every error, with its section, for the audit log."""
        return " ".join(form.problems() for form in self._all() if form.problems())

    def new_guard(self):
        """The unsaved Guard, holding the basic, personal and government values."""
        return self._guard

    def filled_documents(self):
        """The document sections that were filled in. Empty ones are skipped."""
        return [form for form in self._documents if form.has_changed()]

    def describe_new_guard(self):
        """A ChangeSummary of the guard's details. Sensitive fields give only their names."""
        summary = ChangeSummary()
        for form in self._details:
            form.describe_new(summary)
        return summary


# ---------------------------------------------------------------------------
# Employment status
# ---------------------------------------------------------------------------


class StatusChangeForm(forms.Form):
    """A new employment status: one grouped list of status and reason, and an effective date."""

    # The list value joins the status and the reason, like "Let go|End of contract".
    SEPARATOR = "|"

    change = forms.ChoiceField(
        label="New status and reason",
        error_messages={"required": "Choose the new status and reason."},
    )
    effective_date = forms.DateField(
        label="Effective date",
        widget=date_input(),
        help_text="Not in the future, not before he was hired, and not before his last change.",
        error_messages={"required": "Enter the effective date."},
    )

    def __init__(self, guard, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guard = guard
        # Only the statuses he can change to are listed, one HTML optgroup per
        # status with its reasons. This needs no JavaScript, and Django refuses
        # any value that is not in the list.
        self.fields["change"].choices = [("", "Choose the new status and reason")] + [
            (
                status,
                [(self.SEPARATOR.join([status, reason]), self._label(status, reason)) for reason in reasons],
            )
            for status, reasons in guard.employment_status().next_choices()
        ]
        self.fields["change"].widget.attrs["class"] = "form-select"
        self.fields["effective_date"].widget.attrs["class"] = "form-control"

    @staticmethod
    def _label(status, reason):
        """Each option names its status too, so the closed list still reads clearly."""
        return status if reason == status else f"{status}: {reason}"

    @property
    def title(self):
        return "New status"

    def clean(self):
        """The model's own rules decide, through Guard.check_status_change()."""
        cleaned = super().clean()
        choice, effective_date = cleaned.get("change"), cleaned.get("effective_date")
        if choice and effective_date:
            status, reason = choice.split(self.SEPARATOR, 1)
            cleaned["status"], cleaned["reason"] = status, reason
            try:
                self._guard.check_status_change(status, reason, effective_date)
            except ValidationError as error:
                for message in error.messages:
                    self.add_error(None, message)
        return cleaned

    def problems(self):
        """Every error message in one line, for the audit log."""
        return " ".join(error for errors in self.errors.values() for error in errors)
