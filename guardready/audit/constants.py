"""
Audit settings. The security alert numbers are PLACEHOLDERS. Change them only here.

Every window and the office hours use Philippine time (Asia/Manila), even though
Django stores timestamps in UTC.
"""

import calendar
from datetime import time
from zoneinfo import ZoneInfo

# The Security alerts page reads this many days of the audit log.
LOOKBACK_DAYS = 7

PH_TIME_ZONE = ZoneInfo("Asia/Manila")

# Failed logins: 5 or more for one typed username within 15 minutes.
FAILED_LOGIN_THRESHOLD = 5
FAILED_LOGIN_WINDOW_MINUTES = 15

# Repeated refusals: 3 or more DENY entries for one logged-in user within 60 minutes.
DENIAL_THRESHOLD = 3
DENIAL_WINDOW_MINUTES = 60

# Many unlocks: 5 or more STEP_UP entries by one user within one day.
UNLOCK_THRESHOLD = 5
UNLOCK_WINDOW_MINUTES = 24 * 60

# Bulk viewing: one user opening 20 or more guard profiles within 10 minutes.
BULK_VIEW_THRESHOLD = 20
BULK_VIEW_WINDOW_MINUTES = 10
# The URL name of the guard profile page in guards/urls.py.
PROFILE_URL_NAME = "guard_profile"

# After hours: office hours are 07:00 to 19:00, Monday to Saturday.
OFFICE_OPENS = time(7, 0)
OFFICE_CLOSES = time(19, 0)
OFFICE_DAYS = [
    calendar.MONDAY,
    calendar.TUESDAY,
    calendar.WEDNESDAY,
    calendar.THURSDAY,
    calendar.FRIDAY,
    calendar.SATURDAY,
]

# Staff are the roles in ROLE_PERMISSIONS that have this permission (Admin/HR).
# Guards do not have it, so their night shifts never count as after hours.
STAFF_PERMISSION = "guards.view_all_guards"

# ---------------------------------------------------------------------------
# Work the system does by itself (Stage 2: python manage.py check_expiry)
# ---------------------------------------------------------------------------

# The audit entry of a system job has no user. It shows these instead. The
# role is only a label in the log. It is not a login role and has no permissions.
SYSTEM_USERNAME = "system"
SYSTEM_ROLE = "System"
