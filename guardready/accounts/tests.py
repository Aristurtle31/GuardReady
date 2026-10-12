"""
Tests for the accounts app: the two roles and the Zero Trust checks.

Run with: python manage.py test accounts
"""

from io import StringIO

from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.roles import ADMIN, GUARD, ROLE_PERMISSIONS
from audit.models import AuditEntry
from guards.models import Guard

# Admin/HR must keep exactly these permissions.
ADMIN_PERMISSIONS = [
    "guards.view_dashboard",
    "guards.view_all_guards",
    "guards.step_up_sensitive",
    "guards.add_guard",
    "guards.manage_credentials",
    "deployment.assign_guard",
    "reports.record_performance",
    "reports.view_summary_report",
    "audit.view_audit_log",
]

GUARD_PERMISSIONS = [
    "guards.view_own_record",
    "guards.step_up_sensitive",
]


def seed():
    """Build the demo data quietly."""
    call_command("seed_demo", stdout=StringIO())


class RoleListTests(TestCase):
    """ROLE_PERMISSIONS in accounts/roles.py."""

    def test_there_are_exactly_two_roles(self):
        self.assertEqual(set(ROLE_PERMISSIONS), {ADMIN, GUARD})

    def test_admin_permissions_did_not_change(self):
        self.assertEqual(ROLE_PERMISSIONS[ADMIN], ADMIN_PERMISSIONS)

    def test_guard_permissions_did_not_change(self):
        self.assertEqual(ROLE_PERMISSIONS[GUARD], GUARD_PERMISSIONS)


class SeedAccountTests(TestCase):
    """The groups and accounts that seed_demo creates."""

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_only_the_two_role_groups_exist(self):
        names = set(Group.objects.values_list("name", flat=True))
        self.assertEqual(names, {ADMIN, GUARD})

    def test_only_the_admin_and_guard1_accounts_exist(self):
        usernames = set(User.objects.values_list("username", flat=True))
        self.assertEqual(usernames, {"admin", "guard1"})

    def test_seed_is_safe_to_run_twice(self):
        seed()
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(Guard.objects.count(), 8)

    def test_admin_account_has_every_admin_permission(self):
        admin = User.objects.get(username="admin")
        for permission in ADMIN_PERMISSIONS:
            with self.subTest(permission=permission):
                self.assertTrue(admin.has_perm(permission))

    def test_an_unknown_account_cannot_log_in_and_is_logged(self):
        response = self.client.post(
            reverse("login"), {"username": "nobody", "password": "nobody123"}
        )
        self.assertEqual(response.status_code, 200)
        entry = AuditEntry.objects.first()
        self.assertEqual(entry.action, AuditEntry.LOGIN)
        self.assertEqual(entry.outcome, AuditEntry.DENIED)
        self.assertEqual(entry.username, "nobody")


class AdminAccessTests(TestCase):
    """Admin/HR still opens every screen that exists."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.guard = Guard.objects.get(user__username="guard1")

    def setUp(self):
        self.client.login(username="admin", password="admin123")

    def test_admin_opens_every_screen(self):
        urls = [
            reverse("dashboard"),
            reverse("guard_list"),
            reverse("add_guard"),
            reverse("audit_log"),
            reverse("guard_profile", args=[self.guard.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_contact_number_is_masked_before_step_up(self):
        response = self.client.get(reverse("guard_profile", args=[self.guard.pk]))
        page = response.content.decode()
        self.assertIn(self.guard.masked_contact(), page)
        self.assertNotIn(self.guard.contact_number, page)


class GuardAccessTests(TestCase):
    """A guard sees only his own record. Admin pages are refused and logged."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.own = Guard.objects.get(user__username="guard1")
        cls.other = Guard.objects.exclude(pk=cls.own.pk).first()

    def setUp(self):
        self.client.login(username="guard1", password="guard123")

    def test_guard_opens_his_own_profile(self):
        response = self.client.get(reverse("guard_profile", args=[self.own.pk]))
        self.assertEqual(response.status_code, 200)

    def test_admin_pages_are_refused_and_logged_as_deny(self):
        urls = [
            reverse("dashboard"),
            reverse("guard_list"),
            reverse("add_guard"),
            reverse("audit_log"),
            reverse("guard_profile", args=[self.other.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                entry = AuditEntry.objects.first()
                self.assertEqual(entry.action, AuditEntry.DENY)
                self.assertEqual(entry.outcome, AuditEntry.DENIED)
                self.assertEqual(entry.username, "guard1")
                self.assertEqual(entry.role, GUARD)


class StepUpPermissionTests(TestCase):
    """Step-up is decided by the step_up_sensitive permission, not by the role name."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.own = Guard.objects.get(user__username="guard1")
        cls.other = Guard.objects.exclude(pk=cls.own.pk).first()

    def step_up(self, username, password, guard):
        self.client.login(username=username, password=password)
        return self.client.post(
            reverse("step_up", args=[guard.pk]),
            {"password": password, "reason": "Checking the file"},
        )

    def test_admin_can_step_up_for_any_guard(self):
        self.assertEqual(self.step_up("admin", "admin123", self.other).status_code, 302)

    def test_guard_can_step_up_for_his_own_record(self):
        self.assertEqual(self.step_up("guard1", "guard123", self.own).status_code, 302)

    def test_guard_cannot_step_up_for_another_guard(self):
        self.assertEqual(self.step_up("guard1", "guard123", self.other).status_code, 403)

    def test_without_the_permission_the_step_up_is_refused(self):
        permission = Permission.objects.get(
            content_type__app_label="guards", codename="step_up_sensitive"
        )
        Group.objects.get(name=GUARD).permissions.remove(permission)
        self.assertEqual(self.step_up("guard1", "guard123", self.own).status_code, 403)