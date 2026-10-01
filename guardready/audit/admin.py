"""
Django admin for the superuser only (see config/urls.py).
Our models are read only here. All normal work goes through our own views
so that it is logged.
"""

from django.contrib import admin

from .models import AuditEntry


class ReadOnlyAdmin(admin.ModelAdmin):
    """Admin screens that can look but never add, edit, or delete."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEntry)
class AuditEntryAdmin(ReadOnlyAdmin):
    list_display = ["id", "timestamp", "username", "role", "action", "target_type", "target_id", "outcome", "sensitive"]
    list_filter = ["action", "outcome", "sensitive"]
    search_fields = ["username", "details"]
