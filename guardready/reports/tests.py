"""
Tests for compliance reports (Stage 5) and the guard reports, attendance and
evaluations (Stage 4).

Run with: python manage.py test reports
"""

import csv
from datetime import time, timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models import Q
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEntry, RecordLockedError
from deployment.models import Assignment, ClientSite
from guards.constants import EXPIRING_SOON, GUARD_TYPES, LESP_LICENSE, LTO, SHOW_LEFT
from guards.dates import long_date, nice_date
from guards.models import AgencyNotice, AgencyPermit, Credential, CredentialVersion, Guard
from reports import constants
from reports.models import AttendanceRecord, Evaluation

from .base import Report, ReportSection, safe_cell
from .compliance import (
    COMPLIANCE_REPORTS,
    ClientReport,
    ComplianceReport,
    GovernmentReport,
    NpcReport,
    OtherGovernmentReport,
    SosiaReport,
)
from .forms import default_period
from .guard_reports import GuardReport, Punctuality, SummaryReport

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
        # Test setup only. The app has no way to delete a permit or a notice.
        AgencyNotice.objects.filter(permit__kind=LTO).delete()
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


class CredentialChangesSectionTests(ComplianceTestCase):
    """
    The SOSIA change history prints each renewal's old and new expiry date.
    Stage 3 moved the lookup of the new values into CredentialVersion.new_values().
    """

    def test_each_seeded_renewal_prints_its_old_and_new_expiry(self):
        body = report_body(self.print_report(SosiaReport, sections=["changes"]))
        versions = CredentialVersion.objects.select_related("credential")
        self.assertEqual(versions.count(), 2)  # Juan's NBI and Joel's drug test
        for version in versions:
            with self.subTest(document=version.credential.doc_type):
                old, new = long_date(version.old_expires), long_date(version.credential.expires)
                self.assertIn(f"<td>{old}</td><td>{new}</td>", body)

    def test_two_renewals_each_print_the_expiry_that_replaced_them(self):
        admin = User.objects.get(username="admin")
        lesp = Guard.objects.get(employee_no="GR-0002").get_credential(LESP_LICENSE)
        first = lesp.expires
        second, third = first + timedelta(days=10), first + timedelta(days=20)
        lesp.renew("LESP-A", lesp.issued, second, admin)
        lesp.renew("LESP-B", lesp.issued, third, admin)
        body = report_body(self.print_report(SosiaReport, sections=["changes"]))
        self.assertIn(f"<td>{long_date(first)}</td><td>{long_date(second)}</td>", body)
        self.assertIn(f"<td>{long_date(second)}</td><td>{long_date(third)}</td>", body)


# ---------------------------------------------------------------------------
# Stage 4: the one Report base class, guard reports, attendance, evaluations
# ---------------------------------------------------------------------------


def duty(day, time_in=None, absent=False, start=time(6, 0)):
    """An unsaved attendance record with chosen times. status() only reads it."""
    return AttendanceRecord(date=day, scheduled_start=start, time_in=time_in, absent=absent)


def read_csv(response):
    """The rows of a downloaded CSV file, without the byte order mark."""
    return list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))


def every_sensitive_value():
    """Birth dates, contact numbers, addresses, government numbers and medical results."""
    values = set()
    for guard in Guard.objects.all():
        values.update(
            value
            for value in [
                guard.contact_number,
                guard.home_address,
                guard.sss_number,
                guard.tin_number,
                guard.philhealth_number,
            ]
            if value
        )
        if guard.birth_date:
            values.update([long_date(guard.birth_date), nice_date(guard.birth_date)])
    values.update(value for value in Credential.objects.values_list("result", flat=True) if value)
    values.update(
        value for value in CredentialVersion.objects.values_list("old_result", flat=True) if value
    )
    return values


class ReportBaseTests(SimpleTestCase):
    """One report base class for every report, with one CSV writer."""

    def test_the_base_classes_cannot_be_used_on_their_own(self):
        with self.assertRaises(TypeError):
            Report(None, None, None)
        with self.assertRaises(TypeError):
            ReportSection(None)
        with self.assertRaises(TypeError):
            ComplianceReport({}, [], None)

    def test_every_report_extends_the_one_base_class(self):
        self.assertEqual(ComplianceReport.__bases__, (Report,))
        for report_class in [GuardReport, SummaryReport, *COMPLIANCE_REPORTS.values()]:
            with self.subTest(report=report_class.__name__):
                self.assertTrue(issubclass(report_class, Report))

    def test_there_is_only_one_csv_writer(self):
        self.assertIn("write_csv", vars(Report))
        classes = [ComplianceReport, GovernmentReport, GuardReport, SummaryReport]
        for report_class in classes + list(COMPLIANCE_REPORTS.values()):
            with self.subTest(report=report_class.__name__):
                self.assertNotIn("write_csv", vars(report_class))

    def test_a_report_gets_its_number_only_once(self):
        report = SummaryReport(None, None, None)
        self.assertEqual(report.number, "")
        entry = AuditEntry(pk=42, timestamp=timezone.now())
        report.assign_number(entry)
        self.assertEqual(report.number, "GR-RPT-000042")
        with self.assertRaises(ValueError):
            report.assign_number(AuditEntry(pk=43, timestamp=timezone.now()))
        self.assertEqual(report.number, "GR-RPT-000042")

    def test_a_cell_that_looks_like_a_formula_becomes_plain_text(self):
        cases = {
            "=SUM(A1:A9)": "'=SUM(A1:A9)",
            "+639171234567": "'+639171234567",
            "-1": "'-1",
            "@cmd": "'@cmd",
            "Juan Dela Cruz": "Juan Dela Cruz",
            "": "",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(safe_cell(value), expected)
        self.assertEqual(safe_cell(5), 5)


class PunctualityTests(SimpleTestCase):
    """Punctuality counts on time, late and absent. An absence is not on time."""

    def test_the_counts_and_the_rate(self):
        day = timezone.localdate()
        grace = constants.LATE_GRACE_MINUTES
        records = [
            duty(day, time_in=time(5, 50)),  # early
            duty(day, time_in=time(6, grace)),  # inside the grace period
            duty(day, time_in=time(6, grace + 1)),  # late
            duty(day, absent=True),
        ]
        punctuality = Punctuality(records)
        counts = (punctuality.duties, punctuality.on_time, punctuality.late, punctuality.absent)
        self.assertEqual(counts, (4, 2, 1, 1))
        self.assertEqual((punctuality.rate(), punctuality.rate_text()), (50, "50%"))

    def test_no_duties_means_no_rate(self):
        punctuality = Punctuality([])
        self.assertIsNone(punctuality.rate())
        self.assertEqual(punctuality.rate_text(), constants.NO_DUTIES)


class GuardReportTestCase(TestCase):
    """Shared setup for the Stage 4 tests: the demo data and an admin login."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.admin = User.objects.get(username="admin")

    def setUp(self):
        self.today = timezone.localdate()
        self.start, self.end = default_period()
        self.client.login(**ADMIN_LOGIN)

    def guard(self, employee_no):
        return Guard.objects.get(employee_no=employee_no)

    def report_entries(self):
        return AuditEntry.objects.filter(action=AuditEntry.REPORT)

    def last_seeded_duty(self, guard):
        """The newest attendance day the seed recorded for this guard."""
        return AttendanceRecord.objects.filter(guard=guard).first().date


class PerformanceRuleTests(GuardReportTestCase):
    """The model rules behind the attendance and evaluation forms."""

    def test_posting_on_follows_his_postings(self):
        juan = self.guard("GR-0001")  # Main Lobby from 150 to 21 days ago, then Mall Entrance A
        cases = [(0, "Mall Entrance A"), (21, "Mall Entrance A"), (22, "Main Lobby"),
                 (150, "Main Lobby"), (151, None)]
        for days_ago, expected in cases:
            with self.subTest(days_ago=days_ago):
                posting = juan.posting_on(self.today - timedelta(days=days_ago))
                self.assertEqual(posting.post.name if posting else None, expected)
        # Rowena's posting ended 10 days ago, so that day she was no longer posted.
        rowena = self.guard("GR-0006")
        self.assertIsNone(rowena.posting_on(self.today - timedelta(days=10)))
        self.assertEqual(rowena.posting_on(self.today - timedelta(days=11)).post.name, "Mall Entrance A")

    def test_a_duty_takes_its_post_and_shift_start_from_that_days_posting(self):
        juan, joel = self.guard("GR-0001"), self.guard("GR-0003")
        old_day = self.today - timedelta(days=60)  # Main Lobby, before the seeded duties
        day_duty = AttendanceRecord.record(juan, old_day, time(6, 2), False, self.admin)
        self.assertEqual(
            (day_duty.post.name, day_duty.scheduled_start, day_duty.status()),
            ("Main Lobby", time(6, 0), constants.ON_TIME),
        )
        night_duty = AttendanceRecord.record(joel, self.today, None, True, self.admin)
        self.assertEqual(
            (night_duty.post.name, night_duty.scheduled_start, night_duty.status()),
            ("Stockroom", time(18, 0), constants.ABSENT),
        )

    def test_every_broken_duty_rule_is_named(self):
        juan, rowena = self.guard("GR-0001"), self.guard("GR-0006")
        tomorrow = self.today + timedelta(days=1)
        cases = [
            (juan, self.last_seeded_duty(juan), time(6, 0), False, "is already recorded"),
            (rowena, self.today, None, True, "Rowena Villanueva was not posted on"),
            (juan, tomorrow, time(6, 0), False, "The date cannot be in the future."),
            (juan, self.today, time(6, 0), True, "An absent guard cannot have a time in."),
            (juan, self.today, None, False, "Enter the time in, or mark the guard as absent."),
        ]
        for guard, day, time_in, absent, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesMessage(ValidationError, message):
                    AttendanceRecord.record(guard, day, time_in, absent, self.admin)
        self.assertFalse(AttendanceRecord.objects.filter(date__gte=self.today).exists())

    def test_the_evaluation_rules(self):
        mario = self.guard("GR-0002")
        good = {category: 4 for category in constants.EVALUATION_CATEGORIES}
        evaluation = Evaluation.record(mario, self.today, good, "  Alert at the gate.  ", self.admin)
        self.assertEqual(
            (evaluation.average(), evaluation.remarks, evaluation.evaluator),
            (4.0, "Alert at the gate.", self.admin),
        )
        cases = [
            (self.today + timedelta(days=1), good, "The date cannot be in the future."),
            (mario.date_hired - timedelta(days=1), good, "before the hire date"),
            (self.today, {**good, "Honesty": 6}, "Honesty must be a score from 1 to 5."),
            (self.today, {**good, "Discipline": 0}, "Discipline must be a score from 1 to 5."),
        ]
        for day, scores, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesMessage(ValidationError, message):
                    Evaluation.record(mario, day, scores, "", self.admin)
        self.assertEqual(Evaluation.objects.filter(guard=mario, date=self.today).count(), 1)

    def test_averages_over_many_evaluations(self):
        joel = self.guard("GR-0003")  # (5, 4, 5, 5, 5) and (5, 5, 5, 5, 5) in the seed
        evaluations = list(Evaluation.objects.filter(guard=joel))
        self.assertEqual(Evaluation.category_averages(evaluations)["Attitude"], 4.5)
        self.assertEqual(Evaluation.overall_average(evaluations), 4.9)
        self.assertEqual(Evaluation.category_averages([]), {})
        self.assertIsNone(Evaluation.overall_average([]))

    def test_attendance_and_evaluations_are_append_only(self):
        for record in (AttendanceRecord.objects.first(), Evaluation.objects.first()):
            with self.subTest(model=type(record).__name__):
                with self.assertRaises(RecordLockedError):
                    record.save()
                with self.assertRaises(RecordLockedError):
                    record.delete()


class GuardReportPageTests(GuardReportTestCase):
    """The summary and one guard's report on screen."""

    def test_the_default_period_is_the_last_90_days(self):
        self.assertEqual(self.end, self.today)
        self.assertEqual((self.end - self.start).days + 1, constants.DEFAULT_PERIOD_DAYS)

    def test_the_summary_lists_current_guards_with_their_numbers(self):
        response = self.client.get(reverse("summary_report"))
        self.assertEqual(response.status_code, 200)
        lines = response.context["report"].lines()
        self.assertEqual(len(lines), 8)
        self.assertNotIn("Noel Castillo", [guard.full_name for guard, cells in lines])

        juan = self.guard("GR-0001")
        [cells] = [cells for guard, cells in lines if guard == juan]
        punctuality = Punctuality(AttendanceRecord.for_guard(juan, self.start, self.end))
        evaluations = list(Evaluation.for_guard(juan, self.start, self.end))
        self.assertGreater(punctuality.duties, 0)
        expected = [
            "Juan Dela Cruz",
            "GR-0001",
            juan.guard_type,
            punctuality.duties,
            punctuality.on_time,
            punctuality.late,
            punctuality.absent,
            punctuality.rate_text(),
            len(evaluations),
            f"{Evaluation.overall_average(evaluations):.2f}",
        ]
        self.assertEqual(cells, expected)
        self.assertContains(response, reverse("guard_report", args=[juan.pk]))
        entry = AuditEntry.objects.first()
        self.assertEqual((entry.action, entry.target_type), (AuditEntry.VIEW, "SummaryReport"))

    def test_the_filters_list_guards_who_left_or_one_guard_type(self):
        left = self.client.get(reverse("summary_report"), {"show": SHOW_LEFT})
        self.assertEqual(
            [guard.employee_no for guard, cells in left.context["report"].lines()], ["GR-0009"]
        )
        armed = self.client.get(reverse("summary_report"), {"guard_type": GUARD_TYPES[1]})
        names = {guard.full_name for guard, cells in armed.context["report"].lines()}
        self.assertEqual(names, {"Mario Reyes", "Elmer Bautista", "Danilo Ocampo"})
        # The Download CSV button sends the same filters.
        for response, name, value in [(left, "show", SHOW_LEFT), (armed, "guard_type", GUARD_TYPES[1])]:
            hidden = f'<input type="hidden" name="{name}" value="{value}">'
            self.assertContains(response, hidden, html=True)

    def test_a_bad_period_shows_the_errors_and_the_default_period(self):
        cases = [
            (self.today, self.today + timedelta(days=1), "The period cannot end in the future."),
            (self.today, self.today - timedelta(days=5), "The start date cannot be after the end date."),
        ]
        for start, end, message in cases:
            with self.subTest(message=message):
                response = self.client.get(
                    reverse("summary_report"), {"start": start.isoformat(), "end": end.isoformat()}
                )
                self.assertContains(response, message)
                report = response.context["report"]
                self.assertEqual((report.period_start, report.period_end), (self.start, self.end))

    def test_the_guard_report_shows_his_duties_and_evaluations(self):
        juan = self.guard("GR-0001")
        url = reverse("guard_report", args=[juan.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        summary, attendance, evaluations = response.context["report"].built_sections
        duties = AttendanceRecord.for_guard(juan, self.start, self.end).count()
        self.assertEqual(attendance.row_count, duties)
        self.assertEqual(evaluations.row_count, Evaluation.for_guard(juan, self.start, self.end).count())
        self.assertIn(["Duties", duties], summary.rows)
        for text in ["Summary for the period", "Attendance in the period",
                     "Character evaluations in the period", juan.guard_type]:
            with self.subTest(text=text):
                self.assertContains(response, text)
        active = f'<a class="nav-link active" aria-current="page" href="{url}">Report</a>'
        self.assertContains(response, active, html=True)
        self.assertContains(response, reverse("record_attendance", args=[juan.pk]))
        self.assertContains(response, reverse("add_evaluation", args=[juan.pk]))
        entry = AuditEntry.objects.first()
        self.assertEqual(
            (entry.action, entry.target_type, entry.target_id),
            (AuditEntry.VIEW, "GuardReport", str(juan.pk)),
        )

    def test_a_shorter_period_shows_only_its_own_duties(self):
        juan = self.guard("GR-0001")
        week_start = self.today - timedelta(days=6)
        response = self.client.get(
            reverse("guard_report", args=[juan.pk]),
            {"start": week_start.isoformat(), "end": self.today.isoformat()},
        )
        attendance = response.context["report"].built_sections[1]
        in_week = AttendanceRecord.objects.filter(guard=juan, date__gte=week_start)
        self.assertEqual(attendance.row_count, in_week.count())
        self.assertLess(attendance.row_count, AttendanceRecord.objects.filter(guard=juan).count())
        self.assertEqual(response.context["filters"]["start"], week_start)

    def test_the_menu_and_the_profile_link_to_the_reports(self):
        juan = self.guard("GR-0001")
        menu_link = f'<a class="nav-link" href="{reverse("summary_report")}">Guard reports</a>'
        self.assertContains(self.client.get(reverse("dashboard")), menu_link, html=True)
        tab = f'<a class="nav-link" href="{reverse("guard_report", args=[juan.pk])}">Report</a>'
        self.assertContains(self.client.get(reverse("guard_profile", args=[juan.pk])), tab, html=True)


class GuardReportCsvTests(GuardReportTestCase):
    """The CSV downloads: one REPORT entry each, its number in the file name, nothing sensitive."""

    def download_summary(self, **changes):
        data = {"start": "", "end": "", "show": "current", "guard_type": ""}
        data.update(changes)
        return self.client.post(reverse("summary_report_csv"), data)

    def download_guard(self, guard):
        return self.client.post(reverse("guard_report_csv", args=[guard.pk]), {"start": "", "end": ""})

    def test_the_summary_csv_writes_one_report_entry_and_uses_its_number(self):
        before = AuditEntry.objects.count()
        response = self.download_summary()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(AuditEntry.objects.count(), before + 1)  # the REPORT entry, no VIEW
        entry = self.report_entries().get()
        self.assertEqual(
            (entry.target_type, entry.target_id, entry.username, entry.sensitive),
            ("SummaryReport", "current", "admin", False),
        )
        self.assertIn("Rows exported: 8", entry.details)
        number = f"GR-RPT-{entry.pk:06d}"
        self.assertEqual(
            response["Content-Disposition"], f'attachment; filename="{number}-guard-summary-report.csv"'
        )
        rows = read_csv(response)
        self.assertEqual(rows[0], ["Guard Summary Report"])
        self.assertIn(["Report number", number], rows)
        header = rows.index(SummaryReport.sections()[0](None).columns())
        self.assertEqual(len(rows[header + 1:]), 8)

    def test_downloading_again_gives_a_new_number(self):
        first, second = self.download_summary(), self.download_summary()
        newest, oldest = self.report_entries().values_list("pk", flat=True)
        self.assertIn(f"GR-RPT-{oldest:06d}", first["Content-Disposition"])
        self.assertIn(f"GR-RPT-{newest:06d}", second["Content-Disposition"])

    def test_the_guard_csv_has_his_three_tables(self):
        joel = self.guard("GR-0003")
        response = self.download_guard(joel)
        entry = self.report_entries().get()
        self.assertEqual((entry.target_type, entry.target_id), ("GuardReport", str(joel.pk)))
        self.assertIn("Guards exported: 1 | Rows exported:", entry.details)
        file_name = f"GR-RPT-{entry.pk:06d}-guard-report-gr-0003.csv"
        self.assertIn(f'filename="{file_name}"', response["Content-Disposition"])
        rows = read_csv(response)
        for title in ["Summary for the period", "Attendance in the period",
                      "Character evaluations in the period"]:
            with self.subTest(title=title):
                self.assertIn([title], rows)
        self.assertIn(["Guard", joel.summary()], rows)
        evaluation_rows = [row for row in rows if len(row) == 9 and row[1] == "Liza Ramos"]
        self.assertEqual(len(evaluation_rows), Evaluation.objects.filter(guard=joel).count())

    def test_no_csv_file_or_report_page_has_sensitive_data(self):
        values = every_sensitive_value()
        self.assertTrue(values)
        pages = [
            self.download_summary(),
            self.download_summary(show=SHOW_LEFT),
            self.client.get(reverse("summary_report")),
        ]
        for guard in Guard.objects.all():
            pages.append(self.download_guard(guard))
            pages.append(self.client.get(reverse("guard_report", args=[guard.pk])))
        for response in pages:
            body = response.content.decode("utf-8-sig")
            for value in values:
                self.assertNotIn(value, body)

    def test_a_formula_in_the_remarks_is_exported_as_plain_text(self):
        juan = self.guard("GR-0001")
        scores = {category: 4 for category in constants.EVALUATION_CATEGORIES}
        formula = '=HYPERLINK("http://example.com","Click")'
        Evaluation.record(juan, self.today, scores, formula, self.admin)
        rows = read_csv(self.download_guard(juan))
        remarks = [row[-1] for row in rows if row and row[0] == long_date(self.today)]
        self.assertEqual(remarks, ["'" + formula])

    def test_a_csv_needs_a_post_and_a_good_period(self):
        juan = self.guard("GR-0001")
        for url in [reverse("summary_report_csv"), reverse("guard_report_csv", args=[juan.pk])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertFalse(self.report_entries().exists())

        yesterday = self.today - timedelta(days=1)
        response = self.download_summary(start=self.today.isoformat(), end=yesterday.isoformat())
        self.assertRedirects(response, reverse("summary_report"))
        refused = self.report_entries().get()
        self.assertEqual(refused.outcome, AuditEntry.DENIED)
        self.assertIn("The start date cannot be after the end date.", refused.details)


class PerformanceFormTests(GuardReportTestCase):
    """The attendance and evaluation forms: saved through the model, and every refusal logged."""

    def record(self, guard, **data):
        return self.client.post(reverse("record_attendance", args=[guard.pk]), data)

    def evaluate(self, guard, **changes):
        data = {"date": self.today.isoformat()}
        data.update({category.lower(): "4" for category in constants.EVALUATION_CATEGORIES})
        data.update(changes)
        return self.client.post(reverse("add_evaluation", args=[guard.pk]), data)

    def last_create(self):
        return AuditEntry.objects.filter(action=AuditEntry.CREATE).first()

    def test_recording_a_duty_saves_it_and_logs_it(self):
        juan = self.guard("GR-0001")
        response = self.record(juan, date=self.today.isoformat(), time_in="06:12")
        self.assertRedirects(response, reverse("guard_report", args=[juan.pk]))
        record = AttendanceRecord.objects.get(guard=juan, date=self.today)
        self.assertEqual(
            (record.post, record.recorded_by, record.status(), record.minutes_late()),
            (juan.current_assignment().post, self.admin, constants.LATE, 12),
        )
        entry = self.last_create()
        self.assertEqual(
            (entry.outcome, entry.target_type, entry.target_id),
            (AuditEntry.SUCCESS, "AttendanceRecord", str(record.pk)),
        )
        self.assertIn("Late by 12 minutes (time in 6:12 AM)", entry.details)

    def test_an_absence_can_be_recorded(self):
        joel = self.guard("GR-0003")
        self.record(joel, date=self.today.isoformat(), absent="on")
        record = AttendanceRecord.objects.get(guard=joel, date=self.today)
        self.assertEqual((record.status(), record.time_in), (constants.ABSENT, None))

    def test_a_refused_duty_saves_nothing_and_is_logged(self):
        juan, rowena = self.guard("GR-0001"), self.guard("GR-0006")
        tomorrow = self.today + timedelta(days=1)
        before = AttendanceRecord.objects.count()
        cases = [
            (juan, {"date": self.last_seeded_duty(juan).isoformat(), "time_in": "06:00"},
             "is already recorded"),
            (rowena, {"date": self.today.isoformat(), "absent": "on"}, "was not posted on"),
            (juan, {"date": tomorrow.isoformat(), "time_in": "06:00"}, "cannot be in the future"),
        ]
        for guard, data, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.record(guard, **data), message)
                entry = self.last_create()
                self.assertEqual(
                    (entry.outcome, entry.target_type, entry.target_id),
                    (AuditEntry.DENIED, "Guard", str(guard.pk)),
                )
                self.assertIn(message, entry.details)
        self.assertEqual(AttendanceRecord.objects.count(), before)

    def test_adding_an_evaluation_saves_it_and_logs_the_scores(self):
        mario = self.guard("GR-0002")
        response = self.evaluate(mario, honesty="5", remarks="Calm during the fire drill.")
        self.assertRedirects(response, reverse("guard_report", args=[mario.pk]))
        evaluation = Evaluation.objects.get(guard=mario, date=self.today)
        self.assertEqual(
            (evaluation.honesty, evaluation.average(), evaluation.evaluator), (5, 4.2, self.admin)
        )
        entry = self.last_create()
        self.assertEqual((entry.target_type, entry.target_id), ("Evaluation", str(evaluation.pk)))
        self.assertIn("Honesty 5", entry.details)
        self.assertIn("Average 4.20, with remarks", entry.details)

    def test_a_refused_evaluation_saves_nothing_and_is_logged(self):
        mario = self.guard("GR-0002")
        before = Evaluation.objects.count()
        tomorrow = self.today + timedelta(days=1)
        cases = [
            ({"date": tomorrow.isoformat()}, "The date cannot be in the future."),
            ({"date": (mario.date_hired - timedelta(days=1)).isoformat()}, "before the hire date"),
            ({"discipline": "6"}, "not one of the available choices"),
            ({"alertness": ""}, "Choose a score for alertness."),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.evaluate(mario, **data), message)
                self.assertEqual(self.last_create().outcome, AuditEntry.DENIED)
        self.assertEqual(Evaluation.objects.count(), before)


class GuardReportRefusedTests(GuardReportTestCase):
    """guard1 is refused on every guard report page and form, even for his own record."""

    def setUp(self):
        super().setUp()
        self.client.logout()
        self.client.login(**GUARD_LOGIN)

    def test_guard1_is_refused_on_every_guard_report_page(self):
        juan, mario = self.guard("GR-0001"), self.guard("GR-0002")
        counts = (AttendanceRecord.objects.count(), Evaluation.objects.count())
        attempts = [
            ("get", reverse("summary_report")),
            ("get", reverse("guard_report", args=[juan.pk])),
            ("get", reverse("guard_report", args=[mario.pk])),
            ("get", reverse("record_attendance", args=[juan.pk])),
            ("get", reverse("add_evaluation", args=[juan.pk])),
            ("post", reverse("summary_report_csv")),
            ("post", reverse("guard_report_csv", args=[juan.pk])),
            ("post", reverse("record_attendance", args=[juan.pk])),
            ("post", reverse("add_evaluation", args=[juan.pk])),
        ]
        data = {"date": self.today.isoformat(), "time_in": "06:00", "start": "", "end": ""}
        for method, url in attempts:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 403)
                entry = AuditEntry.objects.first()
                self.assertEqual((entry.action, entry.username), (AuditEntry.DENY, "guard1"))
        self.assertEqual((AttendanceRecord.objects.count(), Evaluation.objects.count()), counts)
        changes = AuditEntry.objects.filter(action__in=[AuditEntry.REPORT, AuditEntry.CREATE])
        self.assertFalse(changes.exists())

    def test_guard1_sees_no_report_link_or_tab(self):
        juan = self.guard("GR-0001")
        response = self.client.get(reverse("guard_profile", args=[juan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("summary_report"))
        self.assertNotContains(response, reverse("guard_report", args=[juan.pk]))
