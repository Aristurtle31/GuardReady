"""Constants for attendance, evaluations, and compliance reports."""

# A guard is late if he timed in more than this many minutes after the
# scheduled start of his shift.
LATE_GRACE_MINUTES = 5

# Character evaluation categories. The Evaluation model has one field for
# each, named the same in lower case (discipline, attitude, ...).
EVALUATION_CATEGORIES = ["Discipline", "Attitude", "Appearance", "Honesty", "Alertness"]

LOWEST_SCORE = 1
HIGHEST_SCORE = 5

# Attendance statuses
ON_TIME = "On time"
LATE = "Late"
ABSENT = "Absent"

# ---------------------------------------------------------------------------
# Compliance reports (Stage 5)
# ---------------------------------------------------------------------------

# PLACEHOLDERS. Ask the agency owner for the real values (CLAUDE.md open item 5).
AGENCY_NAME = "Agency name (placeholder)"
AGENCY_ADDRESS = "Agency address (placeholder)"

# The LTO number comes from the License to Operate on the Agency permits page.
# When none is on file, or it has expired, the header prints this instead.
LTO_NOT_ON_FILE = "LTO not on file"

# The report number is the ID of the REPORT audit entry, for example GR-RPT-000123.
REPORT_NUMBER_PREFIX = "GR-RPT-"
REPORT_NUMBER_DIGITS = 6

# Printed at the end of every compliance report. Do not reword it.
CONFIDENTIALITY_NOTE = (
    "This report contains personal data protected under the Data Privacy Act of 2012 "
    "(RA 10173). It is released only for the purpose stated above. Do not copy or share "
    "it for any other purpose."
)

# Short texts printed inside report tables.
STILL_POSTED = "Still posted"
NONE_LISTED = "None"
NAME_NOT_ON_FILE = "Name not on file"
YES = "Yes"
NO = "No"
