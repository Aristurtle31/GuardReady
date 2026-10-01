"""Small service functions for guards. Business rules stay in the models."""

from django.db.models import Q

from . import constants as c
from .models import Guard


def all_guards():
    """Every guard, with credentials loaded in one extra query."""
    return Guard.objects.prefetch_related("credentials")


def search_guards(query):
    """Every word must match a first name, last name, or employee number."""
    guards = all_guards()
    for word in query.split():
        guards = guards.filter(
            Q(first_name__icontains=word)
            | Q(last_name__icontains=word)
            | Q(employee_no__icontains=word)
        )
    return guards


def filter_by_readiness(guards, readiness):
    """Keep only guards with this readiness. An unknown value keeps everyone."""
    if readiness not in c.READINESS_LEVELS:
        return list(guards)
    return [guard for guard in guards if guard.readiness() == readiness]


def readiness_counts(guards):
    """How many guards are Cleared, Expiring soon, and Not cleared."""
    counts = {level: 0 for level in c.READINESS_LEVELS}
    for guard in guards:
        counts[guard.readiness()] += 1
    return counts
