"""
Tests for the guards app: Add Guard, Edit Guard, and the document forms.

Run with: python manage.py test guards
"""

import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from django.utils.text import slugify

from accounts.roles import ADMIN, GUARD, ROLE_PERMISSIONS
from accounts.stepup import STARTED_KEY
from audit.models import AuditEntry, RecordLockedError

from . import constants as c
from .models import Credential, CredentialVersion, Guard

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
