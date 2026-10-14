"""
Constants for guards, credentials, and expiry notices.

Change a rule here and the whole app follows it.
The validity periods are PLACEHOLDERS from the handoff spec. They must be
confirmed against current PNP SOSIA rules before the final version.
"""

from django.utils.text import slugify

# Credential kinds. Each kind has its own proxy model.
LICENSE = "License"
CLEARANCE = "Clearance"
MEDICAL = "MedicalCert"
TRAINING = "TrainingCert"
CREDENTIAL_KIND_CHOICES = [
    (LICENSE, "License"),
    (CLEARANCE, "Clearance"),
    (MEDICAL, "Medical certificate"),
    (TRAINING, "Training certificate"),
]

# The six documents every guard needs.
LESP_LICENSE = "LESP License"
NBI_CLEARANCE = "NBI Clearance"
POLICE_CLEARANCE = "Police Clearance"
DRUG_TEST = "Drug Test"
NEURO_EXAM = "Neuro-Psychiatric Exam"
BASIC_COURSE = "Basic Security Guard Course"

REQUIRED_DOCUMENTS = [
    LESP_LICENSE,
    NBI_CLEARANCE,
    POLICE_CLEARANCE,
    DRUG_TEST,
    NEURO_EXAM,
    BASIC_COURSE,
]
DOCUMENT_CHOICES = [(doc, doc) for doc in REQUIRED_DOCUMENTS]

# The name of each document in a URL, like "nbi-clearance". The profile
# template makes the same name with Django's slugify filter.
DOCUMENT_SLUGS = {slugify(doc): doc for doc in REQUIRED_DOCUMENTS}

# Which kind (proxy model) each document belongs to.
DOCUMENT_KINDS = {
    LESP_LICENSE: LICENSE,
    NBI_CLEARANCE: CLEARANCE,
    POLICE_CLEARANCE: CLEARANCE,
    DRUG_TEST: MEDICAL,
    NEURO_EXAM: MEDICAL,
    BASIC_COURSE: TRAINING,
}

# Validity periods in months (placeholders, see note at the top).
LICENSE_VALIDITY_MONTHS = 24
CLEARANCE_VALIDITY_MONTHS = 12
DRUG_TEST_VALIDITY_MONTHS = 6
NEURO_EXAM_VALIDITY_MONTHS = 12
TRAINING_VALIDITY_MONTHS = 36

# Expiry notices: how many days before expiry each notice is sent.
# 2 months, 1 month, 2 weeks, 1 week, 1 day. Then "Expired" on the expiry date.
NOTICE_DAYS = [60, 30, 14, 7, 1]
EXPIRED_BAND = 0
NOTICE_BAND_LABELS = {
    60: "2 months",
    30: "1 month",
    14: "2 weeks",
    7: "1 week",
    1: "1 day",
    EXPIRED_BAND: "Expired",
}
# These bands also show in the dashboard banner.
URGENT_BANDS = [7, 1, EXPIRED_BAND]

# Status of one credential.
VALID = "Valid"
EXPIRING_SOON = "Expiring soon"
EXPIRED = "Expired"
NOT_ON_FILE = "Not on file"

# Readiness of a guard. "Expiring soon" is shared with the credential status.
CLEARED = "Cleared"
NOT_CLEARED = "Not cleared"
READINESS_LEVELS = [CLEARED, EXPIRING_SOON, NOT_CLEARED]

# Sensitive guard fields (RA 10173). They are shown and edited only after a
# step-up, and the audit log writes their names, never their values.
PERSONAL_FIELDS = ["birth_date", "contact_number", "home_address"]
GOVERNMENT_NUMBER_FIELDS = ["sss_number", "tin_number", "philhealth_number"]

# Contact number, SSS, TIN and PhilHealth: digits, spaces and dashes, with an
# optional + at the start, and at least one digit. No official number format
# is checked. Ask before adding one.
NUMBER_TEXT_PATTERN = r"^\+?[0-9 -]*[0-9][0-9 -]*$"
NUMBER_TEXT_MESSAGE = "Use only digits, spaces and dashes. A + is allowed at the start."

# ---------------------------------------------------------------------------
# Employment status (guards/status.py has the rules for each one)
# ---------------------------------------------------------------------------

# A guard with no status change on record is Active.
ACTIVE = "Active"
ON_LEAVE = "On leave"
RESIGNED = "Resigned"
LET_GO = "Let go"
EMPLOYMENT_STATUSES = [ACTIVE, ON_LEAVE, RESIGNED, LET_GO]
EMPLOYMENT_STATUS_CHOICES = [(status, status) for status in EMPLOYMENT_STATUSES]

# The reasons each status allows. PLACEHOLDERS, to be confirmed with the agency.
# There is no free text, and no reason may hint at health, a case, or discipline.
# The model keeps these as choices, so changing them needs "makemigrations".
ACTIVE_REASONS = ["Hired", "Back from leave", "Rehired", "Correction"]
ON_LEAVE_REASONS = ["Approved leave"]
RESIGNED_REASONS = ["Resigned"]
LET_GO_REASONS = ["End of contract", "Terminated", "Other"]
STATUS_REASON_CHOICES = [
    (reason, reason)
    for reason in ACTIVE_REASONS + ON_LEAVE_REASONS + RESIGNED_REASONS + LET_GO_REASONS
]

# Why a guard who cannot be posted is refused.
ON_LEAVE_REFUSAL = "On leave"
SEPARATED_REFUSAL = "No longer employed"

# Written in the audit entry when a status change turns his login off or on.
LOGIN_CHANGE_NOTES = {True: "turned back on", False: "turned off"}

# The guard list shows current guards, unless the filter asks for guards who left.
SHOW_CURRENT = "current"
SHOW_LEFT = "left"
EMPLOYMENT_FILTERS = {SHOW_CURRENT: "Current guards", SHOW_LEFT: "Guards who left"}

# ---------------------------------------------------------------------------
# Agency permits: the agency's own papers (guards/models.py AgencyPermit)
# ---------------------------------------------------------------------------

# Permit kinds. Each kind has its own proxy model. Only the LTO for now.
LTO = "LTO"
PERMIT_KIND_CHOICES = [(LTO, "License to Operate (LTO)")]

# The name of each permit in a URL, like "lto".
PERMIT_SLUGS = {slugify(kind): kind for kind, _ in PERMIT_KIND_CHOICES}

# PLACEHOLDER: 5 years. The PNP can set a shorter period, so the expiry date
# is never filled in for HR. HR types the date printed on the permit.
LTO_VALIDITY_MONTHS = 60

# An agency notice names the agency instead of a guard.
AGENCY_NOTICE_NAME = "Agency"

# One line about a permit on the dashboard and the compliance request form.
EXPIRY_TEXTS = {
    VALID: "valid until {date}",
    EXPIRING_SOON: "expires in {days}, on {date}",
    EXPIRED: "expired on {date}",
}
PERMIT_MISSING_TEXT = "not on file"
# Alert color for that line. A missing permit is as serious as an expired one.
PERMIT_ALERT_COLORS = {
    VALID: "success",
    EXPIRING_SOON: "warning",
    EXPIRED: "danger",
    NOT_ON_FILE: "danger",
}

# Guard types. Placeholder list, to be confirmed with the agency.
GUARD_TYPES = [
    "Unarmed Security Guard",
    "Armed Security Guard",
    "Lady Security Guard",
    "Security Officer",
]
GUARD_TYPE_CHOICES = [(guard_type, guard_type) for guard_type in GUARD_TYPES]

# Bootstrap badge color for each status, used by the "badge" template filter.
STATUS_COLORS = {
    VALID: "success",
    CLEARED: "success",
    EXPIRING_SOON: "warning",
    EXPIRED: "danger",
    NOT_CLEARED: "danger",
    NOT_ON_FILE: "secondary",
    ACTIVE: "success",
    ON_LEAVE: "info",
    RESIGNED: "secondary",
    LET_GO: "secondary",
}
