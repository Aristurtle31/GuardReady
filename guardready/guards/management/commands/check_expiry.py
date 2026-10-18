"""
python manage.py check_expiry

Makes today's expiry notices for guard documents and agency permits. Run it
once a day, for example with Windows Task Scheduler. It is safe to run more
than once: a band is never sent twice for the same expiry date. Guards who
left (Resigned, Let go) get no notices.

Each run writes one CREATE entry in the audit log, by "system".
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from audit.models import AuditEntry
from audit.services import log_system_event
from guards.services import check_expiry, notice_summary


class Command(BaseCommand):
    help = "Make today's expiry notices. Safe to run more than once a day."

    @transaction.atomic
    def handle(self, *args, **options):
        notices = check_expiry()
        summary = notice_summary(notices)
        log_system_event(
            AuditEntry.CREATE,
            "Notification",
            "check_expiry",
            details=f"Checked the expiry dates. {summary}",
        )
        self.stdout.write(self.style.SUCCESS(f"Done. {summary}"))
        for notice in notices:
            self.stdout.write(f"  {notice.message()}")
