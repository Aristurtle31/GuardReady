"""
Step-up check for sensitive data.

The user re-enters his password and gives a reason. That unlocks ONE
guard's sensitive data for STEP_UP_SECONDS (120). After that it locks
again by itself. The step-up is kept in the user's session.
"""

import time

from django.conf import settings

from .access import can_step_up

GUARD_KEY = "step_up_guard_id"
STARTED_KEY = "step_up_started_at"


def start_step_up(request, guard):
    """Unlock this guard only. Any earlier step-up is replaced."""
    request.session[GUARD_KEY] = guard.pk
    request.session[STARTED_KEY] = time.time()


def clear_step_up(request):
    request.session.pop(GUARD_KEY, None)
    request.session.pop(STARTED_KEY, None)


def seconds_left(request, guard):
    """Seconds until this guard's data locks again. 0 means locked."""
    if request.session.get(GUARD_KEY) != guard.pk:
        return 0
    used = time.time() - request.session.get(STARTED_KEY, 0)
    left = int(settings.STEP_UP_SECONDS - used)
    if left <= 0:
        clear_step_up(request)
        return 0
    return left


def is_unlocked(request, guard):
    """The role must allow it AND the step-up for this guard must still be fresh."""
    return can_step_up(request.user, guard) and seconds_left(request, guard) > 0
