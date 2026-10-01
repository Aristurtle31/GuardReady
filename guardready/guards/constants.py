"""
Constants for guards, credentials, and expiry notices.

Change a rule here and the whole app follows it.
The validity periods are PLACEHOLDERS from the handoff spec. They must be
confirmed against current PNP SOSIA rules before the final version.
"""

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
}
