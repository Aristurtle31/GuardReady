"""Read-only admin screens for the superuser."""

from django.contrib import admin

from audit.admin import ReadOnlyAdmin

from .models import Credential, CredentialVersion, Guard, Notification


@admin.register(Guard)
class GuardAdmin(ReadOnlyAdmin):
    list_display = ["employee_no", "first_name", "last_name", "guard_type", "rank"]
    search_fields = ["first_name", "last_name", "employee_no"]


@admin.register(Credential)
class CredentialAdmin(ReadOnlyAdmin):
    list_display = ["guard", "doc_type", "number", "issued", "expires"]
    list_filter = ["doc_type"]


@admin.register(CredentialVersion)
class CredentialVersionAdmin(ReadOnlyAdmin):
    list_display = ["credential", "old_number", "old_issued", "old_expires", "changed_by", "changed_at"]


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ["guard", "credential", "band", "expiry_date", "created_date", "status"]
    list_filter = ["band", "status"]
