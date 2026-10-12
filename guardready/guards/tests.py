"""
Tests for the guards app.

Run with: python manage.py test guards
"""

from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ADMIN, GUARD, ROLE_PERMISSIONS
from audit.models import AuditEntry

from . import constants as c
from .models import Guard


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
    user = User.objects.create_user(username=username, password="testpass123")
    user.groups.set([build_group(role)])
    return user


def guard_form_data(employee_no="GR-0009"):
    """A complete and valid set of form values."""
    return {
        "employee_no": employee_no,
        "first_name": "Pedro",
        "last_name": "Alcantara",
        "date_hired": timezone.localdate().isoformat(),
        "rank": "Security Guard",
        "position": "Security Guard",
        "guard_type": c.GUARD_TYPES[0],
        "birth_date": "1996-05-14",
        "contact_number": "09171234509",
        "home_address": "Bangkal, Davao City",
        "sss_number": "34-1234509-9",
        "tin_number": "301-234-509-000",
        "philhealth_number": "12-345678509-9",
    }


class AddGuardAccessTests(TestCase):
    """Who is allowed to reach the add guard screen."""

    def setUp(self):
        self.admin = build_user("admin_test", ADMIN)
        self.guard_user = build_user("guard_test", GUARD)
        self.url = reverse("add_guard")

    def test_admin_can_open_the_form(self):
        self.client.login(username="admin_test", password="testpass123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_guard_is_refused_and_the_refusal_is_logged(self):
        self.client.login(username="guard_test", password="testpass123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        denied = AuditEntry.objects.filter(
            username="guard_test",
            action=AuditEntry.DENY,
            outcome=AuditEntry.DENIED,
        )
        self.assertTrue(denied.exists())

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class AddGuardSaveTests(TestCase):
    """What happens when the form is submitted."""

    def setUp(self):
        self.admin = build_user("admin_test", ADMIN)
        self.client.login(username="admin_test", password="testpass123")
        self.url = reverse("add_guard")

    def test_a_valid_form_creates_the_guard(self):
        response = self.client.post(self.url, guard_form_data(), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Guard.objects.filter(employee_no="GR-0009").exists())

    def test_creating_a_guard_writes_a_sensitive_create_entry(self):
        self.client.post(self.url, guard_form_data())
        guard = Guard.objects.get(employee_no="GR-0009")
        entry = AuditEntry.objects.filter(
            action=AuditEntry.CREATE,
            target_type="Guard",
            target_id=str(guard.pk),
        ).first()
        self.assertIsNotNone(entry)
        self.assertTrue(entry.sensitive)
        self.assertEqual(entry.outcome, AuditEntry.SUCCESS)

    def test_a_new_guard_has_no_documents_so_he_is_not_cleared(self):
        self.client.post(self.url, guard_form_data())
        guard = Guard.objects.get(employee_no="GR-0009")
        self.assertEqual(guard.readiness(), c.NOT_CLEARED)
        self.assertFalse(guard.is_deployable())
        self.assertEqual(len(guard.missing()), len(c.REQUIRED_DOCUMENTS))

    def test_a_duplicate_employee_number_is_refused(self):
        self.client.post(self.url, guard_form_data())
        self.client.post(self.url, guard_form_data())
        self.assertEqual(Guard.objects.filter(employee_no="GR-0009").count(), 1)
        refused = AuditEntry.objects.filter(
            action=AuditEntry.CREATE, outcome=AuditEntry.DENIED
        )
        self.assertTrue(refused.exists())

    def test_a_future_date_hired_is_refused(self):
        data = guard_form_data("GR-0010")
        data["date_hired"] = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.client.post(self.url, data)
        self.assertFalse(Guard.objects.filter(employee_no="GR-0010").exists())