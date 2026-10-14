"""
Tests for compliance reports (Stage 5).

Run with: python manage.py test reports
"""

from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEntry
from deployment.models import Assignment, ClientSite
from guards.constants import EXPIRING_SOON, LTO
from guards.dates import long_date, nice_date
from guards.models import AgencyPermit, Credential, CredentialVersion, Guard
from reports import constants
from reports.models import Evaluation

from .compliance import (
    COMPLIANCE_REPORTS,
    ClientReport,
    NpcReport,
    OtherGovernmentReport,
    SosiaReport,
)

ADMIN_LOGIN = {"username": "admin", "password": "admin123"}
GUARD_LOGIN = {"username": "guard1", "password": "guard123"}


def seed():
    """Build the demo data quietly."""
    call_command("seed_demo", stdout=StringIO())


def report_body(response):
    """Only the printed report, without the navbar and footer around it."""
    page = response.content.decode()
    start = page.index('id="compliance-report"')
    end = page.index("</article>", start)
    return page[start:end]


class ComplianceTestCase(TestCase):
    """Shared setup: demo data, an admin login, and a valid request."""

    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.today = timezone.localdate()
        self.client.login(**ADMIN_LOGIN)

    def request_data(self, report_class, **changes):
        """A valid request for this report, covering the last year, every section ticked."""
        data = {
            "requesting_party": "Test Office",
            "contact_name": "Maria Santos",
            "contact_position": "Records Officer",
            "reference_number": "REQ-2026-0001",
            "purpose": "Checking that the report prints the right data",
            "legal_basis": "Written request on file",
            "site": ClientSite.objects.get(name="Bayview Mall").pk,
            "period_start": (self.today - timedelta(days=365)).isoformat(),
            "period_end": self.today.isoformat(),
            "sections": [section.KEY for section in report_class.sections()],
            "password": ADMIN_LOGIN["password"],
        }
        data.update(changes)
        return data

    def print_report(self, report_class, **changes):
        url = reverse("compliance_request", args=[report_class.KIND])
        return self.client.post(url, self.request_data(report_class, **changes))

    def report_entries(self):
        return AuditEntry.objects.filter(action=AuditEntry.REPORT)


class ClientScopeTests(ComplianceTestCase):
    """A client report covers one site, and never says why a guard is not cleared."""

    def test_client_report_never_shows_another_sites_guards(self):
        start = self.today - timedelta(days=90)
        site = ClientSite.objects.get(name="Bayview Mall")
        response = self.print_report(ClientReport, period_start=start.isoformat(), site=site.pk)
        self.assertEqual(response.status_code, 200)
        body = report_body(response)

        overlapping = Assignment.objects.filter(start_date__lte=self.today).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=start)
        )
        here = set(overlapping.filter(post__site=site).values_list("guard_id", flat=True))
        elsewhere = set(overlapping.exclude(post__site=site).values_list("guard_id", flat=True)) - here
        # The seed data must give guards of both kinds, or this test proves nothing.
        self.assertTrue(here)
        self.assertTrue(elsewhere)

        for guard in Guard.objects.filter(pk__in=here):
            self.assertIn(guard.full_name, body)
        for guard in Guard.objects.filter(pk__in=elsewhere):
            self.assertNotIn(guard.full_name, body)
        for other_site in ClientSite.objects.exclude(pk=site.pk):
            self.assertNotIn(other_site.name, body)

    def test_client_report_shows_only_cleared_or_not_cleared(self):
        body = report_body(self.print_report(ClientReport))
        self.assertIn("Not cleared", body)
        self.assertNotIn("Expiring soon", body)
        # The reason a guard is not cleared is never shown.
        for document in ["NBI Clearance", "Police Clearance", "Drug Test", "Neuro-Psychiatric Exam"]:
            self.assertNotIn(document, body)
        self.assertNotIn("expired", body.lower())

    def test_client_report_has_no_usernames_ips_or_evaluations(self):
        body = report_body(self.print_report(ClientReport))
        self.assertIn("Liza Ramos", body)  # the preparer by full name
        for username in ["admin", "guard1"]:
            self.assertNotIn(username, body)
        self.assertNotIn("127.0.0.1", body)
        for remarks in Evaluation.objects.exclude(remarks="").values_list("remarks", flat=True):
            self.assertNotIn(remarks, body)


class SensitiveDataTests(ComplianceTestCase):
    """No report prints a birth date, address, contact number, government number or medical result."""

    def sensitive_values(self):
        values = set()
        for guard in Guard.objects.all():
            for value in [
                guard.contact_number,
                guard.home_address,
                guard.sss_number,
                guard.tin_number,
                guard.philhealth_number,
            ]:
                if value:
                    values.add(value)
            if guard.birth_date:
                values.add(long_date(guard.birth_date))
                values.add(nice_date(guard.birth_date))
                values.add(guard.birth_date.isoformat())
        values.update(value for value in Credential.objects.values_list("result", flat=True) if value)
        values.update(
            value for value in CredentialVersion.objects.values_list("old_result", flat=True) if value
        )
        return values

    def test_no_report_prints_sensitive_data(self):
        # Unlock Juan's record first, so the access log has a sensitive view and a step-up.
        juan = Guard.objects.get(employee_no="GR-0001")
        self.client.post(
            reverse("step_up", args=[juan.pk]),
            {"password": ADMIN_LOGIN["password"], "reason": "Renewal check before posting"},
        )
        self.client.get(reverse("guard_profile", args=[juan.pk]))

        values = self.sensitive_values()
        self.assertTrue(values)
        for report_class in COMPLIANCE_REPORTS.values():
            with self.subTest(report=report_class.KIND):
                response = self.print_report(report_class)
                self.assertEqual(response.status_code, 200)
                body = report_body(response)
                for value in values:
                    self.assertNotIn(value, body)

    def test_npc_report_never_prints_a_session_key(self):
        response = self.print_report(NpcReport)
        session_key = self.client.session.session_key
        self.assertTrue(session_key)
        self.assertNotIn(session_key, report_body(response))


class ReportEntryTests(ComplianceTestCase):
    """Every print writes exactly one REPORT entry, and its ID is the report number."""

    def test_each_report_writes_exactly_one_report_entry(self):
        for report_class in COMPLIANCE_REPORTS.values():
            with self.subTest(report=report_class.KIND):
                before = self.report_entries().count()
                response = self.print_report(report_class)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.report_entries().count(), before + 1)

                entry = self.report_entries().first()  # newest first
                self.assertEqual(entry.target_type, "ComplianceReport")
                self.assertEqual(entry.target_id, report_class.KIND)
                self.assertEqual(entry.username, "admin")
                self.assertTrue(entry.sensitive)
                self.assertIn(report_class.title(), entry.details)
                self.assertIn("REQ-2026-0001", entry.details)
                self.assertIn("Rows printed:", entry.details)
                self.assertContains(response, f"GR-RPT-{entry.pk:06d}")

    def test_printing_again_gives_a_new_number(self):
        first = self.print_report(SosiaReport)
        second = self.print_report(SosiaReport)
        numbers = list(self.report_entries().values_list("pk", flat=True))
        self.assertEqual(len(numbers), 2)
        newest, oldest = numbers
        self.assertContains(first, f"GR-RPT-{oldest:06d}")
        self.assertContains(second, f"GR-RPT-{newest:06d}")


class RefusalTests(ComplianceTestCase):
    """Zero Trust: a wrong password and a Guard are both refused and logged."""

    def test_wrong_password_is_refused_and_logged(self):
        response = self.print_report(SosiaReport, password="wrong-password")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.report_entries().exists())
        refused = AuditEntry.objects.filter(
            action=AuditEntry.DENY,
            outcome=AuditEntry.DENIED,
            username="admin",
            target_type="ComplianceReport",
            target_id="sosia",
        )
        self.assertEqual(refused.count(), 1)
        self.assertIn("Wrong password", refused.first().details)

    def test_guard_is_refused_and_logged(self):
        self.client.logout()
        self.client.login(**GUARD_LOGIN)
        urls = [reverse("compliance_offices")] + [
            reverse("compliance_request", args=[kind]) for kind in COMPLIANCE_REPORTS
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

        response = self.client.post(
            reverse("compliance_request", args=[ClientReport.KIND]),
            self.request_data(ClientReport, password=GUARD_LOGIN["password"]),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.report_entries().exists())
        refused = AuditEntry.objects.filter(action=AuditEntry.DENY, username="guard1")
        self.assertEqual(refused.count(), len(urls) + 1)


class SectionListTests(ComplianceTestCase):
    """Admin can untick sections, but never add one from another report's list."""

    def test_a_section_from_another_report_is_rejected(self):
        response = self.print_report(SosiaReport, sections=["roster", "access_log"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not one of the available choices")
        self.assertFalse(self.report_entries().exists())

    def test_unticked_sections_are_not_printed(self):
        body = report_body(self.print_report(SosiaReport, sections=["roster"]))
        self.assertIn("Guard roster", body)
        self.assertNotIn("Required documents per guard", body)

    def test_other_government_office_starts_with_nothing_ticked(self):
        self.assertEqual(OtherGovernmentReport.default_section_keys(), [])
        both = len(SosiaReport.sections()) + len(NpcReport.sections())
        self.assertEqual(len(OtherGovernmentReport.sections()), both)

    def test_audit_log_shows_both_print_buttons(self):
        response = self.client.get(reverse("audit_log"))
        self.assertContains(response, "Print Government Report")
        self.assertContains(response, "Print Client Report")


class EmploymentStatusReportTests(ComplianceTestCase):
    """Rosters list only guards employed on the print date. History still shows guards who left."""

    def test_sosia_rosters_skip_guards_who_left_but_history_keeps_them(self):
        noel = Guard.objects.get(employee_no="GR-0009")  # resigned in the seed
        for section in ["roster", "documents", "blocked"]:
            with self.subTest(section=section):
                body = report_body(self.print_report(SosiaReport, sections=[section]))
                self.assertNotIn(noel.full_name, body)
        history = report_body(self.print_report(SosiaReport, sections=["deployments"]))
        self.assertIn(noel.full_name, history)

    def test_client_guard_list_skips_guards_who_left_but_the_record_keeps_them(self):
        noel = Guard.objects.get(employee_no="GR-0009")  # was posted at Bayview Mall
        guards = report_body(self.print_report(ClientReport, sections=["site_guards"]))
        self.assertNotIn(noel.full_name, guards)
        record = report_body(self.print_report(ClientReport, sections=["site_deployments"]))
        self.assertIn(noel.full_name, record)


class LtoHeaderTests(ComplianceTestCase):
    """The header prints the License to Operate on file, or "LTO not on file" with a warning."""

    HEADER = "License to Operate (LTO) No.: "

    def form_page(self, report_class=SosiaReport):
        return self.client.get(reverse("compliance_request", args=[report_class.KIND]))

    def test_the_header_prints_the_lto_on_file(self):
        # The seed's LTO expires in 5 days, so it is still valid.
        lto = AgencyPermit.on_file(LTO)
        self.assertEqual(lto.status(), EXPIRING_SOON)
        self.assertEqual((lto.days_left(), lto.notice_band()), (5, 7))
        self.assertNotContains(self.form_page(), "LTO warning")
        for report_class in [SosiaReport, ClientReport]:
            with self.subTest(report=report_class.KIND):
                body = report_body(self.print_report(report_class))
                self.assertIn(self.HEADER + lto.number, body)

    def test_an_expired_lto_prints_lto_not_on_file_with_a_warning(self):
        lto = AgencyPermit.on_file(LTO)
        yesterday = self.today - timedelta(days=1)
        admin = User.objects.get(username="admin")
        lto.renew(lto.number, self.today - timedelta(days=800), yesterday, admin)

        form = self.form_page()
        self.assertContains(form, "LTO warning")
        self.assertContains(form, f"expired on {long_date(yesterday)}")
        body = report_body(self.print_report(SosiaReport))
        self.assertIn(self.HEADER + constants.LTO_NOT_ON_FILE, body)
        self.assertNotIn(lto.number, body)

    def test_no_lto_on_file_prints_lto_not_on_file_with_a_warning(self):
        # Test setup only. The app has no way to delete a permit.
        AgencyPermit.objects.filter(kind=LTO).delete()
        form = self.form_page(ClientReport)
        self.assertContains(form, "LTO warning")
        self.assertContains(form, "not on file. The report header will print")
        body = report_body(self.print_report(ClientReport))
        self.assertIn(self.HEADER + constants.LTO_NOT_ON_FILE, body)

    def test_the_placeholder_number_is_gone(self):
        self.assertFalse(hasattr(constants, "AGENCY_LTO_NUMBER"))
        body = report_body(self.print_report(NpcReport))
        self.assertNotIn("LTO number (placeholder)", body)
        self.assertIn(self.HEADER + AgencyPermit.on_file(LTO).number, body)
