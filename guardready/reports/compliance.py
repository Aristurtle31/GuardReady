"""
Compliance reports: printable reports for a requester outside the agency.

A government office (PNP SOSIA, the National Privacy Commission, or another
office) or a client asks in writing. Each report prints only what that
requester needs. This follows the proportionality rule of the Data Privacy
Act of 2012 (RA 10173): adequate, relevant, necessary, and not excessive.

Never printed on any report: medical results, birth date, home address,
contact number, SSS, TIN, PhilHealth, session keys, and passwords.

OOP in this file
- ABSTRACTION: ComplianceReport and ReportSection are abstract base classes.
- INHERITANCE: ComplianceReport -> GovernmentReport -> SosiaReport,
  NpcReport, OtherGovernmentReport. ComplianceReport -> ClientReport.
  ReportSection -> AuditLogSection and ClientSection -> the printed tables.
- POLYMORPHISM: every report overrides title() and sections(). Every table
  overrides columns() and _collect().
- COMPOSITION: a report owns the tables (sections) it prints.
- FACTORY: COMPLIANCE_REPORTS picks the report class once, like
  ACCOUNT_TYPES and create_account() in the bank activity.
"""

from abc import ABC, abstractmethod

from django.db.models import Q
from django.utils import timezone

from audit.models import AuditEntry
from deployment.models import Assignment
from guards.constants import (
    CLEARED,
    LESP_LICENSE,
    LTO,
    NOT_CLEARED,
    NOT_ON_FILE,
    REQUIRED_DOCUMENTS,
)
from guards.dates import long_date, long_datetime
from guards.models import AgencyPermit, CredentialVersion
from guards.services import all_guards, current_guards

from .constants import (
    ABSENT,
    AGENCY_ADDRESS,
    AGENCY_NAME,
    CONFIDENTIALITY_NOTE,
    LATE,
    LTO_NOT_ON_FILE,
    NAME_NOT_ON_FILE,
    NO,
    NONE_LISTED,
    ON_TIME,
    REPORT_NUMBER_DIGITS,
    REPORT_NUMBER_PREFIX,
    STILL_POSTED,
    YES,
)
from .forms import ClientRequestForm, GovernmentRequestForm
from .models import AttendanceRecord

YES_NO = {True: YES, False: NO}


def person_name(user):
    """A user's full name, never the username. Client reports must not show usernames."""
    return user.get_full_name().strip() or NAME_NOT_ON_FILE


# ---------------------------------------------------------------------------
# Sections: one printed table each
# ---------------------------------------------------------------------------


class ReportSection(ABC):
    """ABSTRACTION: one printed table. Each subclass picks its own columns and rows."""

    KEY = ""
    TITLE = ""
    NOTE = ""

    def __init__(self, report):
        self._report = report
        self._rows = []
        self._guard_ids = set()
        self._built = False

    def __str__(self):
        return f"{self.TITLE}: {len(self._rows)} rows"

    @abstractmethod
    def columns(self):
        """The column headings, in print order."""

    @abstractmethod
    def _collect(self):
        """Run the query and return the rows. Each row is a list of printable values."""

    def build(self):
        """Run the query once. Calling build() again does nothing."""
        if not self._built:
            self._rows = self._collect()
            self._built = True
        return self

    @property
    def title(self):
        return self.TITLE

    @property
    def rows(self):
        return list(self._rows)

    @property
    def row_count(self):
        return len(self._rows)

    @property
    def guard_ids(self):
        """The guards this table names. Counted for the REPORT audit entry."""
        return set(self._guard_ids)

    # --- Helpers the subclasses share ---

    def _guard_row(self, guard, *cells):
        """A row that names a guard. The guard is counted for the audit log."""
        self._guard_ids.add(guard.pk)
        return list(cells)

    def _lesp_cells(self, guard):
        """The LESP number and expiry date, or Not on file."""
        lesp = guard.get_credential(LESP_LICENSE)
        if lesp is None:
            return NOT_ON_FILE, NOT_ON_FILE
        return lesp.number, long_date(lesp.expires)

    def _postings(self):
        """Every assignment that overlaps the report period, at every site."""
        start, end = self._report.period_start, self._report.period_end
        return (
            Assignment.objects.filter(start_date__lte=end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
            .select_related("guard", "post__site")
            .order_by("start_date", "guard__last_name", "guard__first_name", "id")
        )

    @staticmethod
    def _end_text(assignment):
        """The last day of a posting, or Still posted."""
        if assignment.end_date is None:
            return STILL_POSTED
        return long_date(assignment.end_date)


# --- PNP SOSIA sections ---


class GuardRosterSection(ReportSection):
    """Every guard on the roster, with his LESP and readiness on the print date."""

    KEY = "roster"
    TITLE = "Guard roster"
    NOTE = (
        "Guards employed on the date this report was generated, with their readiness "
        "on that date."
    )

    def columns(self):
        return ["Name", "Employee no.", "Guard type", "LESP number", "LESP expiry", "Readiness"]

    def _collect(self):
        rows = []
        for guard in current_guards():
            number, expiry = self._lesp_cells(guard)
            rows.append(
                self._guard_row(
                    guard,
                    guard.full_name,
                    guard.employee_no,
                    guard.guard_type,
                    number,
                    expiry,
                    guard.readiness(),
                )
            )
        return rows


class RequiredDocumentsSection(ReportSection):
    """The status and expiry date of each required document, per guard."""

    KEY = "documents"
    TITLE = "Required documents per guard"
    NOTE = "Document names, statuses and dates only. Medical results are never printed."

    def columns(self):
        return ["Guard", "Employee no.", "Document", "Status", "Expiry date"]

    def _collect(self):
        rows = []
        for guard in current_guards():
            for doc_type in REQUIRED_DOCUMENTS:
                status, expiry = self._document_cells(guard.get_credential(doc_type))
                rows.append(
                    self._guard_row(guard, guard.full_name, guard.employee_no, doc_type, status, expiry)
                )
        return rows

    @staticmethod
    def _document_cells(credential):
        """Status and expiry date of one document, or Not on file."""
        if credential is None:
            return NOT_ON_FILE, ""
        return credential.status(), long_date(credential.expires)


class DeploymentHistorySection(ReportSection):
    """Every posting at every site that overlaps the report period, even of guards who left."""

    KEY = "deployments"
    TITLE = "Deployment history in the period"

    def columns(self):
        return ["Guard", "Site", "Post", "Shift", "From", "To"]

    def _collect(self):
        rows = []
        for posting in self._postings():
            rows.append(
                self._guard_row(
                    posting.guard,
                    posting.guard.full_name,
                    posting.post.site.name,
                    posting.post.name,
                    posting.post.get_shift_display(),
                    long_date(posting.start_date),
                    self._end_text(posting),
                )
            )
        return rows


class BlockedGuardsSection(ReportSection):
    """Guards who cannot be posted on the print date, and the documents behind it."""

    KEY = "blocked"
    TITLE = "Guards blocked from deployment on the print date"

    def columns(self):
        return ["Guard", "Employee no.", "Not on file", "Expired"]

    def _collect(self):
        rows = []
        for guard in current_guards():
            if guard.is_deployable():
                continue
            missing = ", ".join(guard.missing()) or NONE_LISTED
            expired = ", ".join(credential.doc_type for credential in guard.expired()) or NONE_LISTED
            rows.append(self._guard_row(guard, guard.full_name, guard.employee_no, missing, expired))
        return rows


class CredentialChangesSection(ReportSection):
    """Every renewal recorded in the period, with the old and the new expiry date."""

    KEY = "changes"
    TITLE = "Credential change history in the period"
    NOTE = "Old results of medical certificates are never printed."

    def columns(self):
        return ["Guard", "Document", "Old expiry", "New expiry", "Changed by", "Date changed"]

    def _collect(self):
        start, end = self._report.period_start, self._report.period_end
        versions = (
            CredentialVersion.objects.filter(changed_at__date__gte=start, changed_at__date__lte=end)
            .select_related("credential__guard", "changed_by")
            .order_by("changed_at", "id")
        )
        rows = []
        for version in versions:
            credential = version.credential
            rows.append(
                self._guard_row(
                    credential.guard,
                    credential.guard.full_name,
                    credential.doc_type,
                    long_date(version.old_expires),
                    long_date(self._new_expiry(version)),
                    person_name(version.changed_by),
                    long_date(timezone.localtime(version.changed_at).date()),
                )
            )
        return rows

    @staticmethod
    def _new_expiry(version):
        """The expiry date that replaced the old one: the next version's old value, or today's value."""
        later = (
            version.credential.versions.filter(
                Q(changed_at__gt=version.changed_at) | Q(changed_at=version.changed_at, id__gt=version.id)
            )
            .order_by("changed_at", "id")
            .first()
        )
        if later is None:
            return version.credential.expires
        return later.old_expires


# --- National Privacy Commission sections ---


class AuditLogSection(ReportSection):
    """A table read from the audit log for the report period."""

    # Empty means every action.
    ACTION = ""

    def _entries(self):
        """Audit log entries in the period, oldest first."""
        start, end = self._report.period_start, self._report.period_end
        entries = AuditEntry.objects.filter(timestamp__date__gte=start, timestamp__date__lte=end)
        if self.ACTION:
            entries = entries.filter(action=self.ACTION)
        return entries.order_by("timestamp", "id")


class AccessLogSection(AuditLogSection):
    """Every audit log entry in the period. Never a session key."""

    KEY = "access_log"
    TITLE = "Access log for the period"
    NOTE = "Session keys are never printed. Step-up and refusal reasons are in their own sections."

    def columns(self):
        return ["Time", "Username", "Role", "Action", "Target", "Outcome", "Sensitive", "IP address"]

    def _collect(self):
        rows = []
        for entry in self._entries():
            rows.append(
                [
                    long_datetime(entry.timestamp),
                    entry.username,
                    entry.role,
                    entry.action,
                    entry.target(),
                    entry.outcome,
                    YES_NO[entry.sensitive],
                    entry.ip_address or "",
                ]
            )
        return rows


class StepUpSection(AuditLogSection):
    """Every password re-check in the period, with the reason the user typed."""

    KEY = "step_ups"
    TITLE = "Step-up entries with the reason given"
    ACTION = AuditEntry.STEP_UP

    def columns(self):
        return ["Time", "Username", "Role", "Guard record", "Outcome", "Reason given"]

    def _collect(self):
        rows = []
        for entry in self._entries():
            rows.append(
                [
                    long_datetime(entry.timestamp),
                    entry.username,
                    entry.role,
                    entry.target(),
                    entry.outcome,
                    entry.details,
                ]
            )
        return rows


class RefusalsSection(AuditLogSection):
    """Every refused attempt (DENY) in the period."""

    KEY = "refusals"
    TITLE = "Refused attempts (DENY)"
    ACTION = AuditEntry.DENY

    def columns(self):
        return ["Time", "Username", "Role", "Target", "Reason", "IP address"]

    def _collect(self):
        rows = []
        for entry in self._entries():
            rows.append(
                [
                    long_datetime(entry.timestamp),
                    entry.username,
                    entry.role,
                    entry.target(),
                    entry.details,
                    entry.ip_address or "",
                ]
            )
        return rows


class AccessSummarySection(AuditLogSection):
    """Four totals for the period, so the reader sees the whole picture at once."""

    KEY = "summary"
    TITLE = "Summary counts for the period"
    CHANGE_ACTIONS = [AuditEntry.CREATE, AuditEntry.UPDATE, AuditEntry.ASSIGN]

    def columns(self):
        return ["What was counted", "Count"]

    def _collect(self):
        entries = self._entries()
        return [
            [
                "Views of sensitive records",
                entries.filter(action=AuditEntry.VIEW, sensitive=True).count(),
            ],
            [
                "Step-ups granted",
                entries.filter(action=AuditEntry.STEP_UP, outcome=AuditEntry.SUCCESS).count(),
            ],
            [
                "Refused attempts (DENY)",
                entries.filter(action=AuditEntry.DENY).count(),
            ],
            [
                "Changes (CREATE, UPDATE, ASSIGN)",
                entries.filter(action__in=self.CHANGE_ACTIONS, outcome=AuditEntry.SUCCESS).count(),
            ],
        ]


# --- Client sections ---


class ClientSection(ReportSection):
    """A table for a client report. Every query is filtered to the one chosen site."""

    @property
    def site(self):
        return self._report.site

    def _site_postings(self):
        """Postings at this site only that overlap the period. No other site is ever read."""
        return self._postings().filter(post__site=self.site)


class SiteGuardsSection(ClientSection):
    """Guards posted at this site in the period. Readiness is only Cleared or Not cleared."""

    KEY = "site_guards"
    TITLE = "Guards posted at this site"
    NOTE = (
        "Guards still employed on the date this report was generated, with their readiness on "
        "that date. The reason is never shown."
    )
    # A deployable guard (Cleared or Expiring soon) shows as Cleared.
    READINESS_LABELS = {True: CLEARED, False: NOT_CLEARED}

    def columns(self):
        return ["Name", "Guard type", "LESP number", "LESP expiry", "Readiness"]

    def _collect(self):
        guard_ids = set(self._site_postings().values_list("guard_id", flat=True))
        rows = []
        for guard in current_guards(all_guards().filter(pk__in=guard_ids)):
            number, expiry = self._lesp_cells(guard)
            rows.append(
                self._guard_row(
                    guard,
                    guard.full_name,
                    guard.guard_type,
                    number,
                    expiry,
                    self.READINESS_LABELS[guard.is_deployable()],
                )
            )
        return rows


class SiteDeploymentsSection(ClientSection):
    """Postings at this site that overlap the period."""

    KEY = "site_deployments"
    TITLE = "Deployment record at this site"

    def columns(self):
        return ["Guard", "Post", "Shift", "From", "To"]

    def _collect(self):
        rows = []
        for posting in self._site_postings():
            rows.append(
                self._guard_row(
                    posting.guard,
                    posting.guard.full_name,
                    posting.post.name,
                    posting.post.get_shift_display(),
                    long_date(posting.start_date),
                    self._end_text(posting),
                )
            )
        return rows


class SiteAttendanceSection(ClientSection):
    """Duties at this site's posts in the period, counted per guard."""

    KEY = "site_attendance"
    TITLE = "Attendance summary at this site"

    def columns(self):
        return ["Guard", "Duties", "On time", "Late", "Absent"]

    def _collect(self):
        start, end = self._report.period_start, self._report.period_end
        records = (
            AttendanceRecord.objects.filter(post__site=self.site, date__gte=start, date__lte=end)
            .select_related("guard")
            .order_by("guard__last_name", "guard__first_name", "date")
        )
        tallies = {}
        for record in records:
            counts = tallies.setdefault(record.guard, {ON_TIME: 0, LATE: 0, ABSENT: 0})
            counts[record.status()] += 1

        rows = []
        for guard, counts in tallies.items():
            rows.append(
                self._guard_row(
                    guard,
                    guard.full_name,
                    sum(counts.values()),
                    counts[ON_TIME],
                    counts[LATE],
                    counts[ABSENT],
                )
            )
        return rows


# Which tables each requester may receive, in print order.
SOSIA_SECTIONS = (
    GuardRosterSection,
    RequiredDocumentsSection,
    DeploymentHistorySection,
    BlockedGuardsSection,
    CredentialChangesSection,
)
NPC_SECTIONS = (AccessLogSection, StepUpSection, RefusalsSection, AccessSummarySection)
CLIENT_SECTIONS = (SiteGuardsSection, SiteDeploymentsSection, SiteAttendanceSection)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ComplianceReport(ABC):
    """ABSTRACTION: a printable report for one outside requester, showing only what they need."""

    KIND = ""
    ABOUT = ""
    FORM_CLASS = None

    def __init__(self, details, section_keys, prepared_by):
        self._requesting_party = details["requesting_party"]
        self._contact_name = details["contact_name"]
        self._contact_position = details["contact_position"]
        self._reference_number = details["reference_number"]
        self._purpose = details["purpose"]
        self._period_start = details["period_start"]
        self._period_end = details["period_end"]
        self._section_keys = self._allowed_keys(section_keys)
        self._prepared_by = prepared_by
        # Read once, when the report is made. Never a made-up number.
        self._lto_number = self.lto_number_now()
        self._sections = []
        self._entry_id = None
        self._generated_at = None

    def __str__(self):
        return f"{self.title()} {self.number}".strip()

    # --- What every report overrides (POLYMORPHISM) ---

    @classmethod
    @abstractmethod
    def title(cls):
        """The title printed at the top of the report."""

    @classmethod
    @abstractmethod
    def sections(cls):
        """The section classes this report may print, in print order."""

    @classmethod
    def default_section_keys(cls):
        """The sections ticked when the request form opens. By default, all of them."""
        return [section.KEY for section in cls.sections()]

    def _request_rows(self):
        """The request details as label and value pairs. Subclasses add their own."""
        return [
            ("Requesting party", self._requesting_party),
            ("Requested by", f"{self._contact_name}, {self._contact_position}"),
            ("Request reference number", self._reference_number),
            ("Purpose", self._purpose),
            ("Period covered", f"{long_date(self._period_start)} to {long_date(self._period_end)}"),
        ]

    # --- The request pages ---

    @staticmethod
    def lto_number_now():
        """The number of the License to Operate on file, or LTO_NOT_ON_FILE if none is valid."""
        lto = AgencyPermit.usable(LTO)
        return lto.number if lto else LTO_NOT_ON_FILE

    @staticmethod
    def lto_warning():
        """
        The warning for the request form when the header would print
        LTO_NOT_ON_FILE, or "" when a License to Operate is on file and not expired.
        """
        if AgencyPermit.usable(LTO) is not None:
            return ""
        lto = AgencyPermit.overview(LTO)
        return (
            f"{lto['name']}: {lto['text']}. The report header will print "
            f'"{LTO_NOT_ON_FILE}" instead of a license number.'
        )

    @classmethod
    def section_choices(cls):
        return [(section.KEY, section.TITLE) for section in cls.sections()]

    @classmethod
    def make_form(cls, user, data=None):
        """The request form for this report, offering only its own sections."""
        return cls.FORM_CLASS(user, cls.section_choices(), cls.default_section_keys(), data=data)

    @classmethod
    def from_form(cls, form, prepared_by):
        """FACTORY: build the report from a valid request form."""
        return cls(form.request_details(), form.cleaned_data["sections"], prepared_by)

    @classmethod
    def describe(cls):
        """Plain values for the request pages. A template cannot call a class, so it gets a dict."""
        defaults = cls.default_section_keys()
        return {
            "kind": cls.KIND,
            "title": cls.title(),
            "about": cls.ABOUT,
            "sections": [section.TITLE for section in cls.sections()],
            "default_sections": [section.TITLE for section in cls.sections() if section.KEY in defaults],
        }

    # --- Building and numbering, the same for every report ---

    def build(self):
        """Run every ticked section once, in print order. Returns the report."""
        self._sections = [
            section_class(self).build()
            for section_class in self.sections()
            if section_class.KEY in self._section_keys
        ]
        return self

    def assign_number(self, entry):
        """ENCAPSULATION: the report number comes from its REPORT audit entry, and only once."""
        if self._entry_id is not None:
            raise ValueError("This report already has a number.")
        self._entry_id = entry.pk
        self._generated_at = entry.timestamp

    def _allowed_keys(self, keys):
        """Admin may untick sections, but never add one that is not on this report's list."""
        allowed = [section.KEY for section in self.sections()]
        unknown = [key for key in keys if key not in allowed]
        if unknown:
            raise ValueError(f"Not allowed on this report: {', '.join(unknown)}")
        return list(keys)

    # --- Read-only values for the print page and the audit log ---

    @property
    def number(self):
        """Like GR-RPT-000123. Empty until assign_number() runs."""
        if self._entry_id is None:
            return ""
        return f"{REPORT_NUMBER_PREFIX}{self._entry_id:0{REPORT_NUMBER_DIGITS}d}"

    @property
    def period_start(self):
        return self._period_start

    @property
    def period_end(self):
        return self._period_end

    @property
    def built_sections(self):
        return list(self._sections)

    @property
    def prepared_by_name(self):
        return person_name(self._prepared_by)

    @property
    def agency_name(self):
        return AGENCY_NAME

    @property
    def agency_address(self):
        return AGENCY_ADDRESS

    @property
    def agency_lto_number(self):
        """The License to Operate number, or LTO_NOT_ON_FILE. Read when the report was made."""
        return self._lto_number

    @property
    def confidentiality_note(self):
        return CONFIDENTIALITY_NOTE

    def header_rows(self):
        """Everything printed under the title."""
        return [
            ("Report number", self.number),
            ("Date and time generated", f"{long_datetime(self._generated_at)} (Philippine time)"),
            ("Generated by", self.prepared_by_name),
        ] + self._request_rows()

    def guards_printed(self):
        """How many different guards are named anywhere in the report."""
        guard_ids = set()
        for section in self._sections:
            guard_ids |= section.guard_ids
        return len(guard_ids)

    def rows_printed(self):
        return sum(section.row_count for section in self._sections)

    def log_details(self):
        """One line for the REPORT audit entry: the request, the sections, and the counts."""
        parts = [f"Report: {self.title()}"]
        parts += [f"{label}: {value}" for label, value in self._request_rows()]
        parts.append("Sections: " + "; ".join(section.title for section in self._sections))
        parts.append(f"Guards printed: {self.guards_printed()}")
        parts.append(f"Rows printed: {self.rows_printed()}")
        return " | ".join(parts)


class GovernmentReport(ComplianceReport):
    """A report for a government office. Adds the office and the legal basis it cited."""

    OFFICE = ""
    FORM_CLASS = GovernmentRequestForm

    def __init__(self, details, section_keys, prepared_by):
        super().__init__(details, section_keys, prepared_by)
        self._legal_basis = details["legal_basis"]

    def _request_rows(self):
        """POLYMORPHISM: the shared rows plus the office and its legal basis."""
        rows = super()._request_rows()
        rows.append(("Office", self.OFFICE))
        rows.append(("Legal basis or authority stated in the request", self._legal_basis))
        return rows

    @classmethod
    def describe(cls):
        info = super().describe()
        info["office"] = cls.OFFICE
        return info


class SosiaReport(GovernmentReport):
    """For PNP SOSIA: roster, documents, postings, blocked guards, and renewals."""

    KIND = "sosia"
    OFFICE = "PNP SOSIA"
    ABOUT = "PNP SOSIA regulates security agencies and their deployed guards under RA 11917."

    @classmethod
    def title(cls):
        return "Compliance Report for PNP SOSIA"

    @classmethod
    def sections(cls):
        return list(SOSIA_SECTIONS)


class NpcReport(GovernmentReport):
    """For the National Privacy Commission: who opened or changed what, and every refusal."""

    KIND = "npc"
    OFFICE = "National Privacy Commission"
    ABOUT = "The National Privacy Commission enforces the Data Privacy Act of 2012 (RA 10173)."

    @classmethod
    def title(cls):
        return "Data Privacy Compliance Report for the National Privacy Commission"

    @classmethod
    def sections(cls):
        return list(NPC_SECTIONS)


class OtherGovernmentReport(GovernmentReport):
    """For any other government office. Admin picks only the sections its request asks for."""

    KIND = "other"
    OFFICE = "Other government office"
    ABOUT = "Another government office with a written request. You pick the sections it asked for."

    @classmethod
    def title(cls):
        return "Compliance Report for Government Office"

    @classmethod
    def sections(cls):
        return list(SOSIA_SECTIONS) + list(NPC_SECTIONS)

    @classmethod
    def default_section_keys(cls):
        """POLYMORPHISM: nothing is ticked. Admin ticks only what the request asks for."""
        return []


class ClientReport(ComplianceReport):
    """For a client: one site only, and readiness shown only as Cleared or Not cleared."""

    KIND = "client"
    ABOUT = "A company where our guards are posted. The report covers the one site you pick."
    FORM_CLASS = ClientRequestForm

    def __init__(self, details, section_keys, prepared_by):
        super().__init__(details, section_keys, prepared_by)
        self._site = details["site"]

    @property
    def site(self):
        return self._site

    @classmethod
    def title(cls):
        return "Client Compliance Report"

    @classmethod
    def sections(cls):
        return list(CLIENT_SECTIONS)

    def _request_rows(self):
        """POLYMORPHISM: the shared rows plus the client site."""
        rows = super()._request_rows()
        rows.append(("Client site", self._site.name))
        rows.append(("Site address", self._site.address))
        return rows


# FACTORY: the URL names the report, and this dict picks its class once.
COMPLIANCE_REPORTS = {
    report_class.KIND: report_class
    for report_class in (SosiaReport, NpcReport, OtherGovernmentReport, ClientReport)
}

# The offices on the Print Government Report page, in this order.
GOVERNMENT_REPORTS = [SosiaReport, NpcReport, OtherGovernmentReport]


def compliance_report_class(kind):
    """Like create_account() in the bank activity: pick the class once. None if unknown."""
    return COMPLIANCE_REPORTS.get(kind)
