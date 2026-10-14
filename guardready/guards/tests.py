"""
Tests for the guards app: Add Guard, Edit Guard, the document forms, and
employment status.

Run with: python manage.py test guards
"""

import re
import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from django.utils.text import slugify

from accounts.roles import ADMIN, GUARD, ROLE_PERMISSIONS
from accounts.stepup import STARTED_KEY
from audit.models import AuditEntry, RecordLockedError
from deployment.models import Assignment, Post

from . import constants as c
from .dates import long_date, nice_date
from .models import (
    PERMIT_TYPES,
    AgencyNotice,
    AgencyPermit,
    AgencyPermitVersion,
    Credential,
    CredentialVersion,
    EmploymentStatusChange,
    ExpiringDocument,
    Guard,
    LicenseToOperate,
    Notification,
)
from .services import current_guards
from .status import (
    STATUS_CLASSES,
    ActiveStatus,
    EmploymentStatus,
    LetGoStatus,
    OnLeaveStatus,
    ResignedStatus,
    SeparatedStatus,
)

PASSWORD = "testpass123"
ADMIN_LOGIN = {"username": "admin", "password": "admin123"}
GUARD_LOGIN = {"username": "guard1", "password": "guard123"}

# A made-up medical result, so the tests can search for it.
RESULT_TEXT = "Fit for duty 9137"

# The sensitive values the Add Guard tests type in.
PERSONAL_VALUES = {
    "personal-birth_date": "1996-05-14",
    "personal-contact_number": "+63 917-123-4509",
    "personal-home_address": "Purok 9, Bangkal, Davao City",
}
GOVERNMENT_VALUES = {
    "government-sss_number": "34-1234509-9",
    "government-tin_number": "301-234-509-000",
    "government-philhealth_number": "12-345678509-9",
}


def seed():
    """Build the demo data quietly."""
    call_command("seed_demo", stdout=StringIO())


def build_group(role):
    """One group with exactly the permissions listed in accounts/roles.py."""
    group, _ = Group.objects.get_or_create(name=role)
    permissions = []
    for full_name in ROLE_PERMISSIONS[role]:
        app_label, codename = full_name.split(".")
        permissions.append(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    group.permissions.set(permissions)
    return group


def build_user(username, role):
    user = User.objects.create_user(username=username, password=PASSWORD)
    user.groups.set([build_group(role)])
    return user


def document_data(slug, issued_days_ago=10, valid_days=400):
    """
    One filled document section of the Add Guard page. The result is sent for
    every document, but only the two medical sections have a result field, so
    the other four simply ignore it.
    """
    today = timezone.localdate()
    return {
        f"{slug}-number": f"{slug.upper()}-0009",
        f"{slug}-issuer": "Test issuer",
        f"{slug}-issued": (today - timedelta(days=issued_days_ago)).isoformat(),
        f"{slug}-expires": (today + timedelta(days=valid_days)).isoformat(),
        f"{slug}-result": RESULT_TEXT,
    }


def guard_data(employee_no="GR-0009", documents=True, **changes):
    """Values for the whole Add Guard page. All 6 documents expire in 400 days."""
    data = {
        "basic-first_name": "Pedro",
        "basic-last_name": "Alcantara",
        "basic-employee_no": employee_no,
        "basic-date_hired": timezone.localdate().isoformat(),
        "basic-position": "Security Guard",
        "basic-rank": "Security Guard",
        "basic-guard_type": c.GUARD_TYPES[0],
        **PERSONAL_VALUES,
        **GOVERNMENT_VALUES,
    }
    if documents:
        for slug in c.DOCUMENT_SLUGS:
            data.update(document_data(slug))
    data.update(changes)
    return data


def basic_data(guard, **changes):
    """The Edit Guard basic form, filled with the guard's current values."""
    data = {
        "first_name": guard.first_name,
        "last_name": guard.last_name,
        "employee_no": guard.employee_no,
        "date_hired": guard.date_hired.isoformat(),
        "position": guard.position,
        "rank": guard.rank,
        "guard_type": guard.guard_type,
    }
    data.update(changes)
    return data


def sensitive_data(guard, **changes):
    """The personal and government form, filled with the guard's current values."""
    data = {
        "personal-birth_date": guard.birth_date.isoformat(),
        "personal-contact_number": guard.contact_number,
        "personal-home_address": guard.home_address,
        "government-sss_number": guard.sss_number,
        "government-tin_number": guard.tin_number,
        "government-philhealth_number": guard.philhealth_number,
    }
    data.update(changes)
    return data


def renew_data(credential, **changes):
    """A renewal from today, with a new number."""
    today = timezone.localdate()
    data = {
        "number": f"{credential.number}-NEW",
        "issued": today.isoformat(),
        "expires": (today + timedelta(days=365)).isoformat(),
    }
    data.update(changes)
    return data


def all_details():
    """The details of every audit entry, joined, for "never logged" checks."""
    return " ".join(AuditEntry.objects.values_list("details", flat=True))


# ---------------------------------------------------------------------------
# Add Guard
# ---------------------------------------------------------------------------


class AddGuardAccessTests(TestCase):
    """Who is allowed to reach the Add Guard page."""

    def setUp(self):
        build_user("admin_test", ADMIN)
        build_user("guard_test", GUARD)
        self.url = reverse("add_guard")

    def test_admin_can_open_the_form(self):
        self.client.login(username="admin_test", password=PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for section in ["Basic details", "Personal details", "Government numbers", "Paperwork"]:
            self.assertContains(response, section)
        for doc_type in c.REQUIRED_DOCUMENTS:
            self.assertContains(response, doc_type)

    def test_guard_is_refused_and_the_refusal_is_logged(self):
        self.client.login(username="guard_test", password=PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        denied = AuditEntry.objects.filter(
            username="guard_test", action=AuditEntry.DENY, outcome=AuditEntry.DENIED
        )
        self.assertTrue(denied.exists())

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class AddGuardSaveTests(TestCase):
    """What happens when the Add Guard page is submitted."""

    def setUp(self):
        build_user("admin_test", ADMIN)
        self.client.login(username="admin_test", password=PASSWORD)
        self.url = reverse("add_guard")

    def test_all_details_and_six_documents_make_a_cleared_guard(self):
        response = self.client.post(self.url, guard_data())
        guard = Guard.objects.get(employee_no="GR-0009")
        self.assertRedirects(response, reverse("guard_profile", args=[guard.pk]))
        self.assertEqual(guard.credentials.count(), 6)
        self.assertEqual(guard.readiness(), c.CLEARED)
        self.assertEqual(guard.philhealth_number, "12-345678509-9")
        self.assertEqual(guard.get_credential(c.DRUG_TEST).result, RESULT_TEXT)
        # One CREATE for the guard and one for each document.
        created = AuditEntry.objects.filter(action=AuditEntry.CREATE, outcome=AuditEntry.SUCCESS)
        self.assertEqual(created.filter(target_type="Guard").count(), 1)
        self.assertEqual(created.filter(target_type="Credential").count(), 6)

    def test_no_documents_still_saves_and_he_is_not_cleared(self):
        self.client.post(self.url, guard_data(documents=False))
        guard = Guard.objects.get(employee_no="GR-0009")
        self.assertEqual(guard.credentials.count(), 0)
        self.assertEqual(guard.readiness(), c.NOT_CLEARED)
        self.assertEqual(guard.missing(), c.REQUIRED_DOCUMENTS)

    def test_only_basic_details_is_enough(self):
        data = {key: value for key, value in guard_data(documents=False).items()
                if key.startswith("basic-")}
        self.client.post(self.url, data)
        guard = Guard.objects.get(employee_no="GR-0009")
        self.assertIsNone(guard.birth_date)
        self.assertEqual(guard.sss_number, "")
        entry = AuditEntry.objects.get(action=AuditEntry.CREATE, target_type="Guard")
        self.assertFalse(entry.sensitive)

    def test_half_filled_document_section_is_rejected_and_nothing_is_saved(self):
        data = guard_data(documents=False, **{"nbi-clearance-number": "NBI-0009"})
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter the date issued.")
        self.assertContains(response, "Enter the expiry date.")
        self.assertFalse(Guard.objects.exists())
        self.assertFalse(Credential.objects.exists())
        refused = AuditEntry.objects.get(action=AuditEntry.CREATE)
        self.assertEqual(refused.outcome, AuditEntry.DENIED)
        self.assertIn("NBI Clearance", refused.details)

    def test_duplicate_employee_no_is_rejected(self):
        self.client.post(self.url, guard_data())
        response = self.client.post(self.url, guard_data())
        self.assertContains(response, "already belongs to another guard")
        self.assertEqual(Guard.objects.filter(employee_no="GR-0009").count(), 1)
        self.assertEqual(Credential.objects.count(), 6)

    def test_future_date_hired_is_refused(self):
        future = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.client.post(self.url, guard_data(**{"basic-date_hired": future}))
        self.assertFalse(Guard.objects.exists())

    def test_expiry_must_come_after_the_issue_date(self):
        today = timezone.localdate()
        bad = {
            "drug-test-issued": (today - timedelta(days=5)).isoformat(),
            "drug-test-expires": (today - timedelta(days=6)).isoformat(),
        }
        response = self.client.post(self.url, guard_data(**bad))
        self.assertContains(response, "The expiry date must be after the issue date.")
        self.assertFalse(Guard.objects.exists())

    def test_issue_date_cannot_be_in_the_future(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        response = self.client.post(self.url, guard_data(**{"lesp-license-issued": tomorrow}))
        self.assertContains(response, "The issue date cannot be in the future.")
        self.assertFalse(Guard.objects.exists())

    def test_numbers_take_only_digits_spaces_dashes_and_a_leading_plus(self):
        for field, value in [
            ("government-sss_number", "34-12A4509-9"),
            ("government-tin_number", "301/234/509"),
            ("government-philhealth_number", "12-3456+78509"),
            ("personal-contact_number", "0917.123.4509"),
        ]:
            with self.subTest(field=field):
                response = self.client.post(self.url, guard_data(**{field: value}))
                self.assertContains(response, c.NUMBER_TEXT_MESSAGE)
                self.assertFalse(Guard.objects.exists())

    def test_a_failed_save_never_leaves_half_a_guard(self):
        real_add = Guard.add_credential
        calls = []

        def fails_on_the_third_document(guard, *args, **kwargs):
            calls.append(args[0])
            if len(calls) == 3:
                raise RuntimeError("The database stopped in the middle.")
            return real_add(guard, *args, **kwargs)

        with patch.object(Guard, "add_credential", fails_on_the_third_document):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, guard_data())
        self.assertFalse(Guard.objects.exists())
        self.assertFalse(Credential.objects.exists())
        self.assertFalse(AuditEntry.objects.filter(action=AuditEntry.CREATE).exists())

    def test_sensitive_values_never_reach_the_log_or_the_message(self):
        response = self.client.post(self.url, guard_data(), follow=True)
        guard_entry = AuditEntry.objects.get(action=AuditEntry.CREATE, target_type="Guard")
        self.assertTrue(guard_entry.sensitive)
        self.assertIn("PhilHealth number (value hidden)", guard_entry.details)
        self.assertIn('Employee no. "GR-0009"', guard_entry.details)

        medical = AuditEntry.objects.filter(
            action=AuditEntry.CREATE, target_type="Credential", details__contains="Result"
        )
        self.assertEqual(medical.count(), 2)
        self.assertTrue(all(entry.sensitive for entry in medical))

        logged = all_details()
        page_messages = " ".join(str(message) for message in response.context["messages"])
        for value in [*PERSONAL_VALUES.values(), *GOVERNMENT_VALUES.values(), RESULT_TEXT,
                      "May 14, 1996"]:
            with self.subTest(value=value):
                self.assertNotIn(value, logged)
                self.assertNotIn(value, page_messages)

    def test_no_login_account_is_made_for_the_guard(self):
        users_before = User.objects.count()
        self.client.post(self.url, guard_data())
        self.assertEqual(User.objects.count(), users_before)
        self.assertIsNone(Guard.objects.get(employee_no="GR-0009").user)


# ---------------------------------------------------------------------------
# Edit Guard
# ---------------------------------------------------------------------------


class EditGuardTests(TestCase):
    """Basic details need no step-up. Personal and government details do."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.guard = Guard.objects.get(employee_no="GR-0002")

    def setUp(self):
        self.client.login(**ADMIN_LOGIN)
        self.guard.refresh_from_db()

    def step_up(self):
        self.client.post(
            reverse("step_up", args=[self.guard.pk]),
            {"password": ADMIN_LOGIN["password"], "reason": "Updating his records"},
        )

    def test_basic_edit_logs_the_old_and_new_values(self):
        url = reverse("edit_guard", args=[self.guard.pk])
        response = self.client.post(url, basic_data(self.guard, rank="Shift-in-Charge"))
        self.assertRedirects(response, reverse("guard_profile", args=[self.guard.pk]))
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.rank, "Shift-in-Charge")
        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="Guard")
        self.assertFalse(entry.sensitive)
        self.assertIn('Rank from "Head Guard" to "Shift-in-Charge"', entry.details)

    def test_a_required_basic_field_cannot_be_blank(self):
        url = reverse("edit_guard", args=[self.guard.pk])
        response = self.client.post(url, basic_data(self.guard, last_name=""))
        self.assertEqual(response.status_code, 200)
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.last_name, "Reyes")

    def test_an_employee_no_of_another_guard_is_rejected(self):
        url = reverse("edit_guard", args=[self.guard.pk])
        response = self.client.post(url, basic_data(self.guard, employee_no="GR-0001"))
        self.assertContains(response, "already belongs to another guard")
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.employee_no, "GR-0002")

    def test_saving_with_no_change_writes_nothing(self):
        url = reverse("edit_guard", args=[self.guard.pk])
        self.client.post(url, basic_data(self.guard))
        self.assertFalse(AuditEntry.objects.filter(action=AuditEntry.UPDATE).exists())

    def test_sensitive_form_without_step_up_is_refused_and_logged_as_deny(self):
        response = self.client.get(reverse("edit_guard_sensitive", args=[self.guard.pk]))
        self.assertEqual(response.status_code, 403)
        # The refusal page offers the step-up link instead.
        self.assertContains(response, reverse("step_up", args=[self.guard.pk]), status_code=403)
        entry = AuditEntry.objects.first()
        self.assertEqual(entry.action, AuditEntry.DENY)
        self.assertEqual(entry.target_type, "Guard")
        self.assertEqual(entry.target_id, str(self.guard.pk))

    def test_editing_a_sensitive_field_logs_update_without_the_value(self):
        self.step_up()
        old_value = self.guard.philhealth_number
        new_value = "12-999999999-1"
        url = reverse("edit_guard_sensitive", args=[self.guard.pk])
        response = self.client.post(
            url, sensitive_data(self.guard, **{"government-philhealth_number": new_value}),
            follow=True,
        )
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.philhealth_number, new_value)

        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="Guard")
        self.assertTrue(entry.sensitive)
        self.assertIn("PhilHealth number (value hidden)", entry.details)
        self.assertNotIn(new_value, entry.details)
        self.assertNotIn(old_value, entry.details)
        page_messages = " ".join(str(message) for message in response.context["messages"])
        self.assertIn("PhilHealth number", page_messages)
        self.assertNotIn(new_value, page_messages)

    def test_an_optional_field_can_be_cleared(self):
        self.step_up()
        url = reverse("edit_guard_sensitive", args=[self.guard.pk])
        self.client.post(url, sensitive_data(self.guard, **{"personal-home_address": ""}))
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.home_address, "")

    def test_saving_after_the_step_up_ends_is_refused(self):
        self.step_up()
        session = self.client.session
        session[STARTED_KEY] = time.time() - 10_000
        session.save()
        url = reverse("edit_guard_sensitive", args=[self.guard.pk])
        response = self.client.post(
            url, sensitive_data(self.guard, **{"government-tin_number": "999-999-999-000"})
        )
        self.assertEqual(response.status_code, 403)
        self.guard.refresh_from_db()
        self.assertNotEqual(self.guard.tin_number, "999-999-999-000")
        self.assertEqual(AuditEntry.objects.first().action, AuditEntry.DENY)


# ---------------------------------------------------------------------------
# Documents: Add, and Renew or correct
# ---------------------------------------------------------------------------


class DocumentTests(TestCase):
    """Adding a missing document, and renewing or correcting one on file."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.juan = Guard.objects.get(employee_no="GR-0001")
        cls.arnel = Guard.objects.get(employee_no="GR-0008")

    def setUp(self):
        self.client.login(**ADMIN_LOGIN)

    def step_up(self, guard):
        self.client.post(
            reverse("step_up", args=[guard.pk]),
            {"password": ADMIN_LOGIN["password"], "reason": "New medical result"},
        )

    def renew_url(self, guard, doc_type):
        return reverse("renew_document", args=[guard.pk, slugify(doc_type)])

    def test_renewing_saves_the_old_values_in_a_credential_version(self):
        credential = self.juan.get_credential(c.POLICE_CLEARANCE)
        old = (credential.number, credential.issued, credential.expires)
        versions_before = credential.versions.count()

        response = self.client.post(
            self.renew_url(self.juan, c.POLICE_CLEARANCE), renew_data(credential)
        )
        self.assertRedirects(response, reverse("guard_profile", args=[self.juan.pk]))

        self.assertEqual(credential.versions.count(), versions_before + 1)
        version = credential.versions.order_by("-id").first()
        self.assertEqual((version.old_number, version.old_issued, version.old_expires), old)
        credential.refresh_from_db()
        self.assertEqual(credential.number, f"{old[0]}-NEW")
        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="Credential")
        self.assertIn(f'Document number from "{old[0]}" to "{old[0]}-NEW"', entry.details)

    def test_the_new_expiry_is_prefilled_as_today_plus_validity(self):
        credential = self.juan.get_credential(c.NBI_CLEARANCE)
        response = self.client.get(self.renew_url(self.juan, c.NBI_CLEARANCE))
        expected = credential.suggested_expiry(timezone.localdate())
        self.assertContains(response, f'value="{expected.isoformat()}"')

    def test_nothing_changed_is_refused_and_adds_no_history(self):
        credential = self.juan.get_credential(c.NBI_CLEARANCE)
        versions_before = credential.versions.count()
        same = {
            "number": credential.number,
            "issued": credential.issued.isoformat(),
            "expires": credential.expires.isoformat(),
        }
        response = self.client.post(self.renew_url(self.juan, c.NBI_CLEARANCE), same)
        self.assertContains(response, "Nothing was changed")
        self.assertEqual(credential.versions.count(), versions_before)

    def test_the_result_shows_only_after_step_up(self):
        url = self.renew_url(self.juan, c.DRUG_TEST)
        locked = self.client.get(url)
        self.assertNotContains(locked, 'name="result"')
        self.assertContains(locked, "result box is hidden")
        self.step_up(self.juan)
        unlocked = self.client.get(url)
        self.assertContains(unlocked, 'name="result"')

    def test_renewing_a_medical_exam_without_step_up_keeps_the_result(self):
        credential = self.juan.get_credential(c.DRUG_TEST)
        self.client.post(self.renew_url(self.juan, c.DRUG_TEST), renew_data(credential))
        credential.refresh_from_db()
        self.assertEqual(credential.result, "Negative")
        self.assertTrue(credential.number.endswith("-NEW"))

    def test_a_new_result_is_logged_by_name_only(self):
        self.step_up(self.juan)
        credential = self.juan.get_credential(c.NEURO_EXAM)
        data = renew_data(credential, result=RESULT_TEXT)
        self.client.post(self.renew_url(self.juan, c.NEURO_EXAM), data)
        credential.refresh_from_db()
        self.assertEqual(credential.result, RESULT_TEXT)
        version = credential.versions.order_by("-id").first()
        self.assertEqual(version.old_result, "Fit for duty")
        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="Credential")
        self.assertTrue(entry.sensitive)
        self.assertIn("Result (value hidden)", entry.details)
        self.assertNotIn(RESULT_TEXT, all_details())
        self.assertNotIn("Fit for duty", all_details())

    def test_adding_a_missing_document(self):
        today = timezone.localdate()
        url = reverse("add_document", args=[self.arnel.pk, slugify(c.POLICE_CLEARANCE)])
        data = {
            "number": "PC-2026-0008",
            "issuer": "Davao City Police Office",
            "issued": today.isoformat(),
            "expires": (today + timedelta(days=365)).isoformat(),
        }
        self.client.post(url, data)
        credential = self.arnel.get_credential(c.POLICE_CLEARANCE)
        self.assertEqual(credential.number, "PC-2026-0008")
        entry = AuditEntry.objects.get(action=AuditEntry.CREATE, target_type="Credential")
        self.assertEqual(entry.target_id, str(credential.pk))

    def test_an_empty_add_form_is_refused(self):
        url = reverse("add_document", args=[self.arnel.pk, slugify(c.POLICE_CLEARANCE)])
        response = self.client.post(url, {"number": "", "issued": "", "expires": ""})
        self.assertContains(response, "Enter the document number.")
        self.assertIsNone(self.arnel.get_credential(c.POLICE_CLEARANCE))

    def test_add_for_a_document_on_file_goes_to_renew(self):
        url = reverse("add_document", args=[self.juan.pk, slugify(c.NBI_CLEARANCE)])
        response = self.client.get(url)
        self.assertRedirects(response, self.renew_url(self.juan, c.NBI_CLEARANCE))

    def test_the_profile_shows_one_button_per_document(self):
        response = self.client.get(reverse("guard_profile", args=[self.arnel.pk]))
        self.assertContains(response, "Edit guard")
        self.assertContains(response, "Renew or correct", count=5)
        add_url = reverse("add_document", args=[self.arnel.pk, slugify(c.POLICE_CLEARANCE)])
        self.assertContains(response, add_url)


# ---------------------------------------------------------------------------
# ExpiringDocument (Part 3, step 1): the shared base under Credential
# ---------------------------------------------------------------------------


class ExpiringDocumentTests(SimpleTestCase):
    """Credential extends the abstract ExpiringDocument, with no database change."""

    databases = {"default"}  # makemigrations reads the migration history

    def test_no_model_needs_a_new_migration(self):
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out)
        except SystemExit:
            self.fail(f"Django wants a new migration:\n{out.getvalue()}")
        self.assertIn("No changes detected", out.getvalue())

    def test_credential_extends_the_abstract_base(self):
        self.assertTrue(ExpiringDocument._meta.abstract)
        self.assertTrue(issubclass(Credential, ExpiringDocument))
        for name in ["number", "issued", "expires"]:
            with self.subTest(field=name):
                self.assertIs(Credential._meta.get_field(name).model, Credential)

    def test_status_and_notice_band_at_each_edge(self):
        sample = Credential.for_document(c.NBI_CLEARANCE)
        today = timezone.localdate()
        cases = [
            (61, c.VALID, None),
            (60, c.EXPIRING_SOON, 60),
            (31, c.EXPIRING_SOON, 60),
            (30, c.EXPIRING_SOON, 30),
            (8, c.EXPIRING_SOON, 14),
            (7, c.EXPIRING_SOON, 7),
            (1, c.EXPIRING_SOON, 1),
            (0, c.EXPIRED, c.EXPIRED_BAND),
            (-3, c.EXPIRED, c.EXPIRED_BAND),
        ]
        for days, status, band in cases:
            with self.subTest(days=days):
                sample.expires = today + timedelta(days=days)
                self.assertEqual(sample.days_left(), days)
                self.assertEqual(sample.status(), status)
                self.assertEqual(sample.notice_band(), band)

    def test_the_shared_date_checks(self):
        today = timezone.localdate()
        with self.assertRaises(ValidationError):
            Credential.check_values(" ", today, today + timedelta(days=1))
        with self.assertRaises(ValidationError):
            Credential.check_values("A-1", today + timedelta(days=1), today + timedelta(days=9))
        with self.assertRaises(ValidationError):
            Credential.check_values("A-1", today, today)
        Credential.check_values("A-1", today, today + timedelta(days=1))  # no error

    def test_only_a_typed_credential_knows_its_validity(self):
        with self.assertRaises(NotImplementedError):
            Credential(kind=c.LICENSE).validity_months()
        lesp = Credential.for_document(c.LESP_LICENSE)
        self.assertEqual(lesp.validity_months(), c.LICENSE_VALIDITY_MONTHS)


# ---------------------------------------------------------------------------
# Agency permits (Part 3, step 2): the agency's own License to Operate
# ---------------------------------------------------------------------------


def make_lto(days_left, number="LTO-TEST-0001"):
    """Put an LTO on file that expires in days_left days. It was issued 400 days ago."""
    today = timezone.localdate()
    issued = today - timedelta(days=400)
    expires = today + timedelta(days=days_left)
    return AgencyPermit.add(c.LTO, number, issued, expires, issuer="PNP SOSIA")


def permit_data(number="LTO-2026-0100", issued_days_ago=10, valid_days=1800, **changes):
    """The Agency permit form, filled in."""
    today = timezone.localdate()
    data = {
        "number": number,
        "issuer": "PNP SOSIA",
        "issued": (today - timedelta(days=issued_days_ago)).isoformat(),
        "expires": (today + timedelta(days=valid_days)).isoformat(),
    }
    data.update(changes)
    return data


def input_tag(response, name):
    """The HTML <input> tag of one form field, to check what it is filled with."""
    return re.search(rf'<input[^>]*name="{name}"[^>]*>', response.content.decode()).group(0)


class AgencyPermitModelTests(TestCase):
    """The permit classes, renew(), and notices in the right bands."""

    @classmethod
    def setUpTestData(cls):
        cls.hr = User.objects.create(username="hr")

    def test_the_factory_picks_the_proxy_class(self):
        self.assertEqual(PERMIT_TYPES, {c.LTO: LicenseToOperate})
        self.assertTrue(issubclass(AgencyPermit, ExpiringDocument))
        lto = AgencyPermit.for_kind(c.LTO)
        self.assertIsInstance(lto, LicenseToOperate)
        self.assertEqual(lto.validity_months(), 60)  # the placeholder in the approved plan
        self.assertEqual(lto.name(), "License to Operate (LTO)")
        with self.assertRaises(NotImplementedError):
            AgencyPermit(kind=c.LTO).validity_months()
        self.assertIsInstance(make_lto(100), LicenseToOperate)
        self.assertIsInstance(AgencyPermit.on_file(c.LTO), LicenseToOperate)

    def test_only_one_permit_of_each_kind(self):
        make_lto(100)
        with self.assertRaises(ValidationError):
            make_lto(200, number="LTO-TEST-0002")
        self.assertEqual(AgencyPermit.objects.count(), 1)

    def test_renewing_writes_a_version_first(self):
        permit = make_lto(5)
        old = (permit.number, permit.issued, permit.expires)
        today = timezone.localdate()
        permit.renew(" LTO-TEST-0002 ", today, today + timedelta(days=1800), self.hr)

        version = permit.versions.get()
        self.assertEqual((version.old_number, version.old_issued, version.old_expires), old)
        self.assertEqual(version.changed_by, self.hr)
        permit.refresh_from_db()
        self.assertEqual(permit.number, "LTO-TEST-0002")

    def test_nothing_changes_if_the_version_cannot_be_saved(self):
        permit = make_lto(5)
        today = timezone.localdate()
        failing = patch.object(
            AgencyPermitVersion.objects, "create", side_effect=RecordLockedError("test")
        )
        with failing, self.assertRaises(RecordLockedError):
            permit.renew("LTO-TEST-0002", today, today + timedelta(days=1800), self.hr)
        permit.refresh_from_db()
        self.assertEqual(permit.number, "LTO-TEST-0001")

    def test_wrong_dates_are_refused_before_anything_is_saved(self):
        permit = make_lto(5)
        today = timezone.localdate()
        with self.assertRaises(ValidationError):
            permit.renew("LTO-2", today + timedelta(days=1), today + timedelta(days=9), self.hr)
        self.assertFalse(permit.versions.exists())

    def test_permit_notices_are_created_in_the_right_bands(self):
        permit = make_lto(100)
        today = timezone.localdate()
        cases = [
            (61, None), (60, 60), (45, 60), (30, 30), (14, 14), (8, 14),
            (7, 7), (5, 7), (1, 1), (0, c.EXPIRED_BAND), (-2, c.EXPIRED_BAND),
        ]
        for days, band in cases:
            with self.subTest(days=days):
                permit.expires = today + timedelta(days=days)
                permit.save()  # test setup only. HR changes dates through renew().
                notice = permit.make_notice()
                self.assertEqual(notice.band if notice else None, band)
                if notice:
                    self.assertEqual(notice.expiry_date, permit.expires)
                self.assertIsNone(permit.make_notice())  # a band is never sent twice
        self.assertEqual(AgencyNotice.objects.count(), len([b for _, b in cases if b is not None]))

    def test_a_renewal_with_a_new_expiry_starts_the_bands_again(self):
        permit = make_lto(5)
        first = permit.make_notice()
        self.assertEqual(first.band, 7)
        self.assertEqual(
            first.message(),
            f"Agency: License to Operate (LTO) expires in 5 days ({nice_date(permit.expires)}).",
        )
        today = timezone.localdate()
        permit.renew(permit.number, today - timedelta(days=30), today + timedelta(days=3), self.hr)
        second = permit.make_notice()
        self.assertEqual((second.band, second.expiry_date), (7, permit.expires))
        self.assertEqual(permit.notices.count(), 2)

    def test_a_guard_document_uses_the_same_notice_steps(self):
        today = timezone.localdate()
        guard = Guard.objects.create(
            employee_no="GR-0099",
            first_name="Test",
            last_name="Guard",
            guard_type=c.GUARD_TYPES[0],
            date_hired=today,
        )
        credential = guard.add_credential(
            c.NBI_CLEARANCE, "NBI-1", today - timedelta(days=360), today + timedelta(days=5)
        )
        notice = credential.make_notice()
        self.assertIsInstance(notice, Notification)
        self.assertEqual(notice.guard, guard)
        self.assertEqual(
            notice.message(),
            f"Test Guard: NBI Clearance expires in 5 days ({nice_date(credential.expires)}).",
        )
        self.assertIsNone(credential.make_notice())

    def test_a_notice_only_moves_forward(self):
        notice = make_lto(0).make_notice()
        when = nice_date(notice.expiry_date)
        expected = f"Agency: License to Operate (LTO) has expired ({when})."
        self.assertEqual(notice.message(), expected)
        notice.mark_seen()
        notice.resolve()
        with self.assertRaises(ValidationError):
            notice.mark_seen()

    def test_permits_versions_and_notices_are_never_deleted(self):
        permit = make_lto(5)
        notice = permit.make_notice()
        today = timezone.localdate()
        permit.renew("LTO-TEST-0002", today, today + timedelta(days=1800), self.hr)
        version = permit.versions.get()
        for record in (permit, version, notice):
            with self.subTest(record=type(record).__name__):
                with self.assertRaises(RecordLockedError):
                    record.delete()
        with self.assertRaises(RecordLockedError):
            version.save()
        with self.assertRaises(RecordLockedError):
            AgencyPermitVersion.objects.all().delete()

    def test_the_line_for_the_dashboard(self):
        missing = AgencyPermit.overview(c.LTO)
        self.assertEqual(
            (missing["status"], missing["text"], missing["color"]),
            (c.NOT_ON_FILE, "not on file", "danger"),
        )
        permit = make_lto(400)
        today = timezone.localdate()
        cases = [
            (400, c.VALID, "valid until", "success"),
            (5, c.EXPIRING_SOON, "expires in 5 days, on", "warning"),
            (1, c.EXPIRING_SOON, "expires in 1 day, on", "warning"),
            (-1, c.EXPIRED, "expired on", "danger"),
        ]
        for days, status, text, color in cases:
            with self.subTest(days=days):
                permit.expires = today + timedelta(days=days)
                permit.save()  # test setup only
                line = AgencyPermit.overview(c.LTO)
                self.assertEqual((line["status"], line["color"]), (status, color))
                self.assertEqual(line["text"], f"{text} {long_date(permit.expires)}")


class AgencyPermitPageTests(TestCase):
    """The Agency permits page: a list, Add, and Renew or correct. Admin/HR only."""

    @classmethod
    def setUpTestData(cls):
        cls.hr = build_user("hr", ADMIN)
        build_user("guard1", GUARD)

    def setUp(self):
        self.client.login(username="hr", password=PASSWORD)

    def test_the_list_offers_add_when_no_lto_is_on_file(self):
        response = self.client.get(reverse("agency_permits"))
        self.assertContains(response, "Not on file")
        self.assertContains(response, reverse("add_permit", args=["lto"]))
        opened = AuditEntry.objects.first()
        self.assertEqual((opened.action, opened.target_type), (AuditEntry.VIEW, "AgencyPermit"))

    def test_adding_the_lto_is_saved_and_logged(self):
        response = self.client.post(reverse("add_permit", args=["lto"]), permit_data())
        self.assertRedirects(response, reverse("agency_permits"))
        lto = AgencyPermit.on_file(c.LTO)
        self.assertEqual((lto.number, lto.issuer), ("LTO-2026-0100", "PNP SOSIA"))
        entry = AuditEntry.objects.get(action=AuditEntry.CREATE, target_type="AgencyPermit")
        self.assertEqual(entry.target_id, str(lto.pk))
        self.assertIn("LTO-2026-0100", entry.details)
        self.assertContains(self.client.get(reverse("agency_permits")), "LTO-2026-0100")

    def test_the_expiry_date_is_never_filled_in(self):
        add = self.client.get(reverse("add_permit", args=["lto"]))
        self.assertNotIn("value=", input_tag(add, "expires"))
        lto = make_lto(5)
        renew = self.client.get(reverse("renew_permit", args=["lto"]))
        self.assertNotIn("value=", input_tag(renew, "expires"))
        self.assertIn(f'value="{lto.number}"', input_tag(renew, "number"))
        self.assertIn(f'value="{lto.issued.isoformat()}"', input_tag(renew, "issued"))

    def test_the_same_date_checks_as_guard_documents(self):
        cases = {
            "future issue date": permit_data(issued_days_ago=-1),
            "expiry before the issue date": permit_data(valid_days=-20),
            "blank number": permit_data(number=" "),
        }
        for name, data in cases.items():
            with self.subTest(name):
                response = self.client.post(reverse("add_permit", args=["lto"]), data)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(AgencyPermit.on_file(c.LTO))
        refused = AuditEntry.objects.filter(
            action=AuditEntry.CREATE, outcome=AuditEntry.DENIED, target_type="AgencyPermit"
        )
        self.assertEqual(refused.count(), len(cases))

    def test_renewing_through_the_page_writes_a_version_and_logs_the_change(self):
        lto = make_lto(5)
        today = timezone.localdate()
        data = {
            "number": "LTO-2026-0200",
            "issued": today.isoformat(),
            "expires": (today + timedelta(days=1825)).isoformat(),
        }
        response = self.client.post(reverse("renew_permit", args=["lto"]), data)
        self.assertRedirects(response, reverse("agency_permits"))
        version = lto.versions.get()
        self.assertEqual(version.old_number, "LTO-TEST-0001")
        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="AgencyPermit")
        self.assertIn('from "LTO-TEST-0001" to "LTO-2026-0200"', entry.details)
        history = self.client.get(reverse("agency_permits"))
        self.assertContains(history, "LTO-TEST-0001")  # the old number, in the change history

    def test_nothing_changed_is_refused_and_logged(self):
        lto = make_lto(5)
        same = {
            "number": lto.number,
            "issued": lto.issued.isoformat(),
            "expires": lto.expires.isoformat(),
        }
        response = self.client.post(reverse("renew_permit", args=["lto"]), same)
        self.assertContains(response, "Nothing was changed")
        self.assertFalse(lto.versions.exists())
        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_type="AgencyPermit")
        self.assertEqual(entry.outcome, AuditEntry.DENIED)

    def test_add_and_renew_send_you_to_the_right_page(self):
        response = self.client.get(reverse("renew_permit", args=["lto"]))
        self.assertRedirects(response, reverse("add_permit", args=["lto"]))
        make_lto(5)
        response = self.client.get(reverse("add_permit", args=["lto"]))
        self.assertRedirects(response, reverse("renew_permit", args=["lto"]))

    def test_an_unknown_permit_is_not_found(self):
        for name in ["add_permit", "renew_permit"]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name, args=["xyz"])).status_code, 404)

    def test_the_dashboard_shows_the_lto_line(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "License to Operate (LTO)</strong>: not on file.")
        lto = make_lto(400)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, f"No. {lto.number}: valid until {long_date(lto.expires)}.")
        self.assertContains(response, 'class="alert alert-success')

    def test_guard1_is_refused_on_every_permit_page(self):
        make_lto(5)
        self.client.logout()
        self.client.login(username="guard1", password=PASSWORD)
        urls = [
            reverse("agency_permits"),
            reverse("add_permit", args=["lto"]),
            reverse("renew_permit", args=["lto"]),
        ]
        for url in urls:
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    response = method(url, permit_data(number="CHANGED-1"))
                    self.assertEqual(response.status_code, 403)
                    entry = AuditEntry.objects.first()
                    self.assertEqual((entry.action, entry.username), (AuditEntry.DENY, "guard1"))
        self.assertEqual(AgencyPermit.on_file(c.LTO).number, "LTO-TEST-0001")
        self.assertFalse(AgencyPermitVersion.objects.exists())

    def test_only_admin_sees_the_menu_link(self):
        menu_link = f'<a class="nav-link" href="{reverse("agency_permits")}">Agency permits</a>'
        self.assertContains(self.client.get(reverse("dashboard")), menu_link, html=True)
        self.client.logout()
        self.client.login(username="guard1", password=PASSWORD)
        # The refused page still has the guard's own menu, without this link.
        refused = self.client.get(reverse("agency_permits"))
        self.assertContains(refused, "Log out", status_code=403)
        self.assertNotContains(refused, "Agency permits", status_code=403)


# ---------------------------------------------------------------------------
# The Guard role, and no delete anywhere
# ---------------------------------------------------------------------------


class GuardRoleTests(TestCase):
    """guard1 is refused on every new page, even for his own record."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.own = Guard.objects.get(user__username="guard1")
        cls.other = Guard.objects.get(employee_no="GR-0002")

    def setUp(self):
        self.client.login(**GUARD_LOGIN)

    def new_page_urls(self):
        return [
            reverse("add_guard"),
            reverse("edit_guard", args=[self.own.pk]),
            reverse("edit_guard", args=[self.other.pk]),
            reverse("edit_guard_sensitive", args=[self.own.pk]),
            reverse("add_document", args=[self.own.pk, slugify(c.POLICE_CLEARANCE)]),
            reverse("renew_document", args=[self.own.pk, slugify(c.NBI_CLEARANCE)]),
            reverse("change_status", args=[self.own.pk]),
        ]

    def test_guard1_is_refused_on_every_new_page(self):
        guards_before = list(Guard.objects.values_list("pk", "employee_no", "rank"))
        credentials_before = list(Credential.objects.values_list("pk", "number", "expires"))
        for url in self.new_page_urls():
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    response = method(url, renew_data(self.own.get_credential(c.NBI_CLEARANCE)))
                    self.assertEqual(response.status_code, 403)
                    entry = AuditEntry.objects.first()
                    self.assertEqual(entry.action, AuditEntry.DENY)
                    self.assertEqual(entry.username, "guard1")
        self.assertEqual(list(Guard.objects.values_list("pk", "employee_no", "rank")), guards_before)
        self.assertEqual(
            list(Credential.objects.values_list("pk", "number", "expires")), credentials_before
        )

    def test_step_up_does_not_let_guard1_edit_his_own_details(self):
        self.client.post(
            reverse("step_up", args=[self.own.pk]),
            {"password": GUARD_LOGIN["password"], "reason": "Checking my file"},
        )
        response = self.client.get(reverse("edit_guard_sensitive", args=[self.own.pk]))
        self.assertEqual(response.status_code, 403)

    def test_guard1_sees_no_edit_buttons_on_his_profile(self):
        response = self.client.get(reverse("guard_profile", args=[self.own.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("edit_guard", args=[self.own.pk]))
        self.assertNotContains(response, "Renew or correct")


class NoDeleteTests(TestCase):
    """Guards and documents are never deleted. Their history must stay."""

    def app_routes(self, patterns, prefix=""):
        """Every URL of our own apps. The read-only Django admin is checked separately."""
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                if pattern.app_name == "admin":
                    continue
                yield from self.app_routes(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                yield prefix + str(pattern.pattern), pattern.name or ""

    def test_no_url_deletes_a_guard_or_a_document(self):
        routes = list(self.app_routes(get_resolver().url_patterns))
        self.assertTrue(routes)
        for route, name in routes:
            with self.subTest(route=route):
                for word in ["delete", "remove"]:
                    self.assertNotIn(word, route.lower())
                    self.assertNotIn(word, name.lower())

    def test_no_role_has_a_delete_permission(self):
        for role, permissions in ROLE_PERMISSIONS.items():
            for permission in permissions:
                with self.subTest(role=role, permission=permission):
                    self.assertFalse(permission.split(".")[1].startswith("delete_"))

    def test_the_django_admin_cannot_delete_guards_or_documents(self):
        for model in [Guard, Credential, CredentialVersion]:
            with self.subTest(model=model.__name__):
                self.assertFalse(admin.site._registry[model].has_delete_permission(None))

    def test_a_credential_refuses_to_be_deleted(self):
        seed()
        credential = Credential.objects.first()
        with self.assertRaises(RecordLockedError):
            credential.delete()
        self.assertTrue(Credential.objects.filter(pk=credential.pk).exists())

    def test_delete_requests_change_nothing(self):
        seed()
        self.client.login(**ADMIN_LOGIN)
        guard = Guard.objects.get(employee_no="GR-0001")
        guards, credentials = Guard.objects.count(), Credential.objects.count()
        for url in [
            reverse("guard_profile", args=[guard.pk]),
            reverse("edit_guard", args=[guard.pk]),
            reverse("renew_document", args=[guard.pk, slugify(c.NBI_CLEARANCE)]),
        ]:
            with self.subTest(url=url):
                self.client.delete(url)
        self.assertEqual(Guard.objects.count(), guards)
        self.assertEqual(Credential.objects.count(), credentials)


# ---------------------------------------------------------------------------
# Employment status
# ---------------------------------------------------------------------------


class StatusClassTests(SimpleTestCase):
    """Each status class gives the answers in the approved table."""

    # can be assigned, gets notices, counts as current, allows login, can change to
    TABLE = {
        c.ACTIVE: (True, True, True, True, [c.ON_LEAVE, c.RESIGNED, c.LET_GO]),
        c.ON_LEAVE: (False, True, True, True, [c.ACTIVE, c.RESIGNED, c.LET_GO]),
        c.RESIGNED: (False, False, False, False, [c.ACTIVE]),
        c.LET_GO: (False, False, False, False, [c.ACTIVE]),
    }
    REASONS = {
        c.ACTIVE: c.ACTIVE_REASONS,
        c.ON_LEAVE: c.ON_LEAVE_REASONS,
        c.RESIGNED: c.RESIGNED_REASONS,
        c.LET_GO: c.LET_GO_REASONS,
    }

    def test_each_status_answers_like_the_table(self):
        for name, expected in self.TABLE.items():
            with self.subTest(status=name):
                status = STATUS_CLASSES[name]()
                answers = (
                    status.can_be_assigned(),
                    status.gets_notices(),
                    status.counts_as_current(),
                    status.allows_login(),
                    status.next_statuses(),
                )
                self.assertEqual(answers, expected)

    def test_each_status_gives_only_its_own_reasons(self):
        for name, reasons in self.REASONS.items():
            with self.subTest(status=name):
                self.assertEqual(STATUS_CLASSES[name]().reasons(), reasons)

    def test_the_refusal_reasons(self):
        self.assertEqual(ActiveStatus().refusal_reason(), "")
        self.assertEqual(OnLeaveStatus().refusal_reason(), "On leave")
        self.assertEqual(ResignedStatus().refusal_reason(), "No longer employed")
        self.assertEqual(LetGoStatus().refusal_reason(), "No longer employed")

    def test_resigned_and_let_go_extend_the_separated_rules(self):
        for status_class in (ResignedStatus, LetGoStatus):
            with self.subTest(status=status_class.NAME):
                self.assertTrue(issubclass(status_class, SeparatedStatus))
                self.assertTrue(issubclass(status_class, EmploymentStatus))

    def test_the_base_classes_cannot_be_used_on_their_own(self):
        for abstract_class in (EmploymentStatus, SeparatedStatus):
            with self.subTest(base=abstract_class.__name__):
                with self.assertRaises(TypeError):
                    abstract_class()


class EmploymentStatusTests(TestCase):
    """Changing a status: the page, the date rules, the posting, the login, and the log."""

    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.today = timezone.localdate()
        self.client.login(**ADMIN_LOGIN)

    def guard(self, employee_no):
        return Guard.objects.get(employee_no=employee_no)

    def change(self, guard, status, reason, days_ago=0, client=None):
        """Post the change status form, like the admin does."""
        effective_date = self.today - timedelta(days=days_ago)
        return (client or self.client).post(
            reverse("change_status", args=[guard.pk]),
            {"change": f"{status}|{reason}", "effective_date": effective_date.isoformat()},
        )

    def guard_client(self):
        """A second browser, logged in as guard1."""
        client = Client()
        self.assertTrue(client.login(**GUARD_LOGIN))
        return client

    def test_a_guard_with_no_records_is_active(self):
        mario = self.guard("GR-0002")
        self.assertFalse(mario.status_changes.exists())
        self.assertIsInstance(mario.employment_status(), ActiveStatus)
        self.assertIsNone(mario.employment_status().effective_date)

    def test_the_list_offers_only_the_allowed_next_statuses(self):
        mario = self.guard("GR-0002")
        response = self.client.get(reverse("change_status", args=[mario.pk]))
        for status in [c.ON_LEAVE, c.RESIGNED, c.LET_GO]:
            self.assertContains(response, f'<optgroup label="{status}">')
        self.assertNotContains(response, f'<optgroup label="{c.ACTIVE}">')
        # A value that is not in the list is refused, and nothing is saved.
        response = self.change(mario, c.ACTIVE, "Hired")
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(mario.status_changes.exists())

    def test_resigning_closes_the_open_posting_on_the_effective_date(self):
        mario = self.guard("GR-0002")
        posting = mario.current_assignment()
        self.assertIsNotNone(posting)
        response = self.change(mario, c.RESIGNED, "Resigned", days_ago=3)
        self.assertRedirects(response, reverse("guard_profile", args=[mario.pk]))

        effective_date = self.today - timedelta(days=3)
        posting.refresh_from_db()
        self.assertEqual(posting.end_date, effective_date)
        self.assertIsInstance(mario.employment_status(), ResignedStatus)

        entry = AuditEntry.objects.get(action=AuditEntry.UPDATE, target_id=str(mario.pk))
        for text in ['from "Active" to "Resigned"', f"effective {long_date(effective_date)}",
                     'reason "Resigned"', "open posting at"]:
            with self.subTest(text=text):
                self.assertIn(text, entry.details)

    def test_a_date_before_his_posting_started_is_refused(self):
        elmer = self.guard("GR-0005")  # posted 21 days ago
        response = self.change(elmer, c.ON_LEAVE, "Approved leave", days_ago=30)
        self.assertContains(response, "before his current posting started")
        self.assertIsNotNone(elmer.current_assignment())
        self.assertFalse(elmer.status_changes.exists())

    def test_a_future_date_or_a_date_before_date_hired_is_refused(self):
        # Arnel has no open posting, so only the date rules can refuse him.
        arnel = self.guard("GR-0008")
        self.assertIsNone(arnel.current_assignment())
        before_hired = (self.today - arnel.date_hired).days + 1
        cases = [
            (-1, "The effective date cannot be in the future."),
            (before_hired, "The effective date cannot be before he was hired"),
        ]
        for days_ago, message in cases:
            with self.subTest(message=message):
                response = self.change(arnel, c.RESIGNED, "Resigned", days_ago=days_ago)
                self.assertContains(response, message)
        self.assertIsInstance(arnel.employment_status(), ActiveStatus)
        refused = AuditEntry.objects.filter(action=AuditEntry.UPDATE, outcome=AuditEntry.DENIED)
        self.assertEqual(refused.count(), 2)

    def test_a_date_before_his_last_change_is_refused(self):
        joel = self.guard("GR-0003")
        self.change(joel, c.ON_LEAVE, "Approved leave", days_ago=2)
        response = self.change(joel, c.ACTIVE, "Back from leave", days_ago=5)
        self.assertContains(response, "before his last status change")
        self.assertIsInstance(joel.employment_status(), OnLeaveStatus)

    def test_the_latest_change_decides_his_status(self):
        joel = self.guard("GR-0003")  # posted 30 days ago
        self.change(joel, c.ON_LEAVE, "Approved leave", days_ago=10)
        self.change(joel, c.ACTIVE, "Back from leave", days_ago=3)
        self.assertIsInstance(joel.employment_status(), ActiveStatus)
        self.assertEqual([change.status for change in joel.status_history()], [c.ACTIVE, c.ON_LEAVE])

    def test_on_leave_and_resigned_guards_cannot_be_assigned(self):
        """
        Assignment.start() refuses them with the reason. Logging the refusal
        is the job of assign_guard(), which comes in Stage 3.
        """
        admin_user = User.objects.get(username="admin")
        post = Post.objects.get(name="Basement Parking")  # 0 of 1 filled
        cases = [
            ("GR-0003", c.ON_LEAVE, "Approved leave", c.ON_LEAVE_REFUSAL),
            ("GR-0002", c.RESIGNED, "Resigned", c.SEPARATED_REFUSAL),
        ]
        for employee_no, status, reason, refusal in cases:
            with self.subTest(status=status):
                guard = self.guard(employee_no)
                self.change(guard, status, reason)
                with self.assertRaisesMessage(ValidationError, refusal):
                    Assignment.start(guard, post, admin_user)
        self.assertFalse(post.active_assignments().exists())

    def test_a_resigned_guards_login_stops_and_rehiring_restores_it(self):
        juan = self.guard("GR-0001")  # guard1
        logged_in = self.guard_client()

        self.change(juan, c.RESIGNED, "Resigned")
        # His next click finds him logged out, and he cannot log in again.
        response = logged_in.get(reverse("my_record"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertFalse(Client().login(**GUARD_LOGIN))
        entry = AuditEntry.objects.filter(action=AuditEntry.UPDATE).first()
        self.assertIn("Login turned off for user guard1", entry.details)

        self.change(juan, c.ACTIVE, "Rehired")
        self.assertIsInstance(juan.employment_status(), ActiveStatus)
        self.assertTrue(Client().login(**GUARD_LOGIN))
        entry = AuditEntry.objects.filter(action=AuditEntry.UPDATE).first()
        self.assertIn("Login turned back on for user guard1", entry.details)

    def test_guards_who_left_are_not_counted_and_get_no_notices(self):
        """check_expiry() comes in Stage 2. It will ask gets_notices(), checked here."""
        noel = self.guard("GR-0009")  # resigned in the seed
        self.assertFalse(noel.employment_status().gets_notices())
        self.assertNotIn(noel, current_guards())

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["total"], 8)
        self.assertEqual(dashboard.context["left"], 1)
        self.assertEqual(sum(card["count"] for card in dashboard.context["cards"]), 8)

        self.assertNotContains(self.client.get(reverse("guard_list")), noel.full_name)
        left = self.client.get(reverse("guard_list"), {"show": c.SHOW_LEFT})
        self.assertContains(left, noel.full_name)
        self.assertNotContains(left, "Juan Dela Cruz")

    def test_on_leave_guards_still_count_and_are_labelled(self):
        joel = self.guard("GR-0003")
        self.change(joel, c.ON_LEAVE, "Approved leave")
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["total"], 8)
        self.assertEqual(dashboard.context["on_leave"], 1)
        listed = self.client.get(reverse("guard_list"))
        self.assertContains(listed, joel.full_name)
        self.assertContains(listed, ">On leave</span>")

    def test_the_profile_shows_status_and_history_and_a_guard_sees_his_own(self):
        noel = self.guard("GR-0009")
        response = self.client.get(reverse("guard_profile", args=[noel.pk]))
        self.assertContains(response, "Employment status history")
        self.assertContains(response, "Cannot be posted: No longer employed.")

        juan = self.guard("GR-0001")
        own = self.guard_client().get(reverse("guard_profile", args=[juan.pk]))
        self.assertContains(own, "Employment status")
        self.assertContains(own, "since he was hired")
        self.assertNotContains(own, reverse("change_status", args=[juan.pk]))

    def test_guard1_is_refused_on_the_change_status_page(self):
        juan = self.guard("GR-0001")
        client = self.guard_client()
        url = reverse("change_status", args=[juan.pk])
        for method in (client.get, client.post):
            with self.subTest(method=method.__name__):
                response = method(url, {"change": "Resigned|Resigned",
                                        "effective_date": self.today.isoformat()})
                self.assertEqual(response.status_code, 403)
                entry = AuditEntry.objects.first()
                self.assertEqual((entry.action, entry.username), (AuditEntry.DENY, "guard1"))
        self.assertFalse(juan.status_changes.exists())

    def test_the_status_history_is_append_only(self):
        change = EmploymentStatusChange.objects.get(guard__employee_no="GR-0009")
        with self.assertRaises(RecordLockedError):
            change.save()
        with self.assertRaises(RecordLockedError):
            change.delete()
